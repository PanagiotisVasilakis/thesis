import { MapContainer, TileLayer, Polyline } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import UEMarker from './UEMarker';
import CellMarker from './CellMarker';

export default function MapView({ cells, ues, paths, center, onUEClick }) {
    return (
        <MapContainer
            center={center}
            zoom={16}
            className="h-[500px] rounded-lg"
        >
            <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />

            {/* Cell coverage circles */}
            {cells.map((cell) => (
                <CellMarker key={cell.id} cell={cell} />
            ))}

            {/* Paths */}
            {paths.map((path) => (
                <Polyline
                    key={path.id}
                    positions={path.points?.map((p) => [p.latitude, p.longitude]) || []}
                    pathOptions={{ color: path.color || '#3388ff', weight: 3 }}
                />
            ))}

            {/* UE markers */}
            {ues.map((ue) => (
                <UEMarker key={ue.supi} ue={ue} onClick={onUEClick} />
            ))}
        </MapContainer>
    );
}
