import { useState, useEffect } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Circle, Polyline, useMap } from 'react-leaflet';
import { getCells, getUEs, getPaths, getMovingUEs, startAllUEs, stopAllUEs, startUE, stopUE } from '../api/nefClient';
import { getMode, setMode, getUEState } from '../api/mlClient';
import ModeToggle from '../components/ML/ModeToggle';
import SignalPanel from '../components/ML/SignalPanel';
import HandoverHistory from '../components/ML/HandoverHistory';
import L from 'leaflet';

// Fix Leaflet marker icons
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
    iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
    iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
    shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

export default function MapPage() {
    const [cells, setCells] = useState([]);
    const [ues, setUEs] = useState([]);
    const [paths, setPaths] = useState([]);
    const [mlMode, setMlMode] = useState(true);
    const [selectedUE, setSelectedUE] = useState(null);
    const [signalData, setSignalData] = useState(null);
    const [handoverHistory, setHandoverHistory] = useState([]);
    const [center, setCenter] = useState([37.997, 23.819]);
    const [refreshInterval, setRefreshInterval] = useState(null);

    // Load initial data
    useEffect(() => {
        const loadData = async () => {
            try {
                const [cellsRes, uesRes, pathsRes, modeRes] = await Promise.all([
                    getCells(),
                    getUEs(),
                    getPaths(),
                    getMode(),
                ]);
                setCells(cellsRes.data);
                setUEs(uesRes.data);
                setPaths(pathsRes.data);
                setMlMode(modeRes.data.use_ml);

                // Set map center to first cell
                if (cellsRes.data.length > 0) {
                    setCenter([cellsRes.data[0].latitude, cellsRes.data[0].longitude]);
                }
            } catch (error) {
                console.error('Failed to load data:', error);
            }
        };
        loadData();
    }, []);

    // Refresh UE positions periodically
    useEffect(() => {
        const interval = setInterval(async () => {
            try {
                const uesRes = await getUEs();
                setUEs(uesRes.data);
            } catch (error) {
                console.error('Failed to refresh UEs:', error);
            }
        }, 2000);

        return () => clearInterval(interval);
    }, []);

    const handleModeChange = async (useML) => {
        try {
            await setMode(useML);
            setMlMode(useML);
        } catch (error) {
            console.error('Failed to change mode:', error);
        }
    };

    const handleUEClick = async (ue) => {
        setSelectedUE(ue);
        try {
            const res = await getUEState(ue.supi);
            setSignalData(res.data);
        } catch (error) {
            console.error('Failed to get UE state:', error);
            setSignalData(null);
        }
    };

    const handleStartAll = async () => {
        try {
            await startAllUEs();
        } catch (error) {
            console.error('Failed to start UEs:', error);
        }
    };

    const handleStopAll = async () => {
        try {
            await stopAllUEs();
        } catch (error) {
            console.error('Failed to stop UEs:', error);
        }
    };

    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-2xl font-bold text-gray-800">Network Map</h1>
                    <p className="text-gray-500">Visualize cells, UEs, and handovers</p>
                </div>
                <div className="flex gap-2">
                    <button onClick={handleStartAll} className="btn btn-success">
                        ▶️ Start All
                    </button>
                    <button onClick={handleStopAll} className="btn btn-danger">
                        ⏹️ Stop All
                    </button>
                </div>
            </div>

            {/* ML Control Panel */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <ModeToggle mlMode={mlMode} onModeChange={handleModeChange} />
                <SignalPanel ue={selectedUE} signalData={signalData} />
            </div>

            {/* Map */}
            <div className="card">
                <div className="card-body p-0">
                    <MapContainer center={center} zoom={16} className="h-[500px] rounded-lg">
                        <TileLayer
                            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                        />

                        {/* Cell coverage circles */}
                        {cells.map((cell) => (
                            <Circle
                                key={cell.id}
                                center={[cell.latitude, cell.longitude]}
                                radius={cell.radius}
                                pathOptions={{ color: 'blue', fillOpacity: 0.1 }}
                            >
                                <Popup>{cell.name}</Popup>
                            </Circle>
                        ))}

                        {/* Paths */}
                        {paths.map((path) => (
                            <Polyline
                                key={path.id}
                                positions={path.points?.map(p => [p.latitude, p.longitude]) || []}
                                pathOptions={{ color: path.color || '#3388ff', weight: 3 }}
                            />
                        ))}

                        {/* UE markers */}
                        {ues.map((ue) => (
                            <Marker
                                key={ue.supi}
                                position={[ue.latitude, ue.longitude]}
                                eventHandlers={{
                                    click: () => handleUEClick(ue),
                                }}
                            >
                                <Popup>
                                    <div className="min-w-[200px]">
                                        <strong>{ue.name}</strong><br />
                                        SUPI: {ue.supi}<br />
                                        Cell: {ue.cell_id_hex || 'None'}<br />
                                        Speed: {ue.speed}<br />
                                        <div className="flex gap-2 mt-2">
                                            <button
                                                onClick={async () => {
                                                    try {
                                                        await startUE(ue.supi);
                                                    } catch (error) {
                                                        console.error('Failed to start UE:', error);
                                                    }
                                                }}
                                                className="text-xs px-2 py-1 bg-green-500 text-white rounded hover:bg-green-600"
                                            >
                                                ▶️ Start
                                            </button>
                                            <button
                                                onClick={async () => {
                                                    try {
                                                        await stopUE(ue.supi);
                                                    } catch (error) {
                                                        console.error('Failed to stop UE:', error);
                                                    }
                                                }}
                                                className="text-xs px-2 py-1 bg-red-500 text-white rounded hover:bg-red-600"
                                            >
                                                ⏹️ Stop
                                            </button>
                                        </div>
                                    </div>
                                </Popup>
                            </Marker>
                        ))}
                    </MapContainer>
                </div>
            </div>

            {/* Handover History */}
            <HandoverHistory history={handoverHistory} onClear={() => setHandoverHistory([])} />
        </div>
    );
}
