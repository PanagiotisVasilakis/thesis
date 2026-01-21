import { useState, useEffect, useRef } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Circle, Polyline, useMap } from 'react-leaflet';
import { getCells, getUEs, getPaths, getMovingUEs, startAllUEs, stopAllUEs, startUE, stopUE, importScenario, getRecentHandovers } from '../api/nefClient';
import { getMode, setMode, getUEState } from '../api/mlClient';
import ModeToggle from '../components/ML/ModeToggle';
import SignalPanel from '../components/ML/SignalPanel';
import HandoverHistory from '../components/ML/HandoverHistory';
import RealTimeMetrics from '../components/Analytics/RealTimeMetrics';
import RetryModal from '../components/Experiment/RetryModal';
import ClearConfirmModal from '../components/Experiment/ClearConfirmModal';
import { useExperiment } from '../context/ExperimentContext';
import L from 'leaflet';

// Fix Leaflet marker icons
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
    iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
    iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
    shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

export default function MapPage() {
    // Get shared experiment state from context
    const {
        isRetrying,
        currentRetry,
        totalRetries,
        isRunning,
        setIsRunning,
        timeRemaining,
        setTimeRemaining,
        sessionId,
        mlMode,
        setMlMode,
        duration,
        setDuration,
        scenarioName,
        setScenarioName,
        handoverHistory,
        addHandover,
        clearAll,
        startRetries,
        stopRetries,
        prevUEsRef,
    } = useExperiment();

    // Local UI state
    const [cells, setCells] = useState([]);
    const [ues, setUEs] = useState([]);
    const [paths, setPaths] = useState([]);
    const [selectedUE, setSelectedUE] = useState(null);
    const [selectedSignalData, setSelectedSignalData] = useState(null);
    const [showRetryModal, setShowRetryModal] = useState(false);
    const [showClearModal, setShowClearModal] = useState(false);
    const [handoverWsConnected, setHandoverWsConnected] = useState(false);
    const [handoverWsStatus, setHandoverWsStatus] = useState('disconnected');

    const pollIntervalRef = useRef(null);
    const timerIntervalRef = useRef(null);
    const handoverWsRef = useRef(null);
    const processedBackendIdsRef = useRef(new Set());
    const handoverReconnectTimeoutRef = useRef(null);
    const handoverReconnectAttemptRef = useRef(0);
    const signalPollRef = useRef(null);

    // Fetch initial data
    useEffect(() => {
        const fetchData = async () => {
            try {
                const [cellsRes, uesRes, pathsRes, modeRes] = await Promise.all([
                    getCells(),
                    getUEs(),
                    getPaths(),
                    getMode().catch(() => ({ data: { mode: 'hybrid' } })),
                ]);
                setCells(cellsRes.data || []);
                setUEs(uesRes.data || []);
                setPaths(pathsRes.data || []);
                setMlMode(modeRes.data?.mode || 'hybrid');

                // Store initial UE positions when data loads
                if (uesRes.data?.length > 0) {
                    setInitialUEPositions(uesRes.data.map(ue => ({
                        supi: ue.supi,
                        name: ue.name,
                        latitude: ue.latitude,
                        longitude: ue.longitude,
                    })));
                }
            } catch (error) {
                console.error('Error fetching data:', error);
            }
        };
        fetchData();
    }, []);

    // Poll for UE movement when running
    useEffect(() => {
        if (isRunning) {
            const processedBackendIds = processedBackendIdsRef.current;

            pollIntervalRef.current = setInterval(async () => {
                try {
                    const res = await getMovingUEs();
                    const movingUEs = Object.values(res.data || {});

                    // Also fetch real handover events from backend (with actual ML confidence)
                    let backendHandovers = [];
                    if (!handoverWsConnected) {
                        try {
                            const hoRes = await getRecentHandovers(20);
                            backendHandovers = hoRes.data || [];
                        } catch (e) {
                            // Backend endpoint may not exist in older versions
                            console.debug('Backend handovers not available:', e.message);
                        }
                    }

                    // Detect handovers from position changes
                    const newHandovers = [];
                    if (!handoverWsConnected) {
                        movingUEs.forEach(nextUE => {
                            const prevUE = prevUEsRef.current[nextUE.supi];
                            if (prevUE && prevUE.cell_id_hex && nextUE.cell_id_hex &&
                                prevUE.cell_id_hex !== nextUE.cell_id_hex) {

                                // Try to find matching backend handover with real ML confidence
                                const backendMatch = backendHandovers.find(bh =>
                                    bh.ue === (nextUE.name || nextUE.supi) &&
                                    !processedBackendIds.has(`${bh.ue}-${bh.time}`)
                                );

                                let confidence = null;
                                let method;

                                if (backendMatch && backendMatch.confidence !== null) {
                                    // Use REAL ML confidence from backend
                                    confidence = backendMatch.confidence;
                                    // Use backend method if available, otherwise derive from mode
                                    method = backendMatch.method || (mlMode === 'ml' ? 'ML' : mlMode === 'hybrid' ? 'Hybrid' : 'A3 Event');
                                    processedBackendIds.add(`${backendMatch.ue}-${backendMatch.time}`);
                                } else {
                                    // No backend match - derive method from current mode
                                    method = mlMode === 'ml' ? 'ML' : mlMode === 'hybrid' ? 'Hybrid' : 'A3 Event';
                                }

                                const prevRSRP = Number.isFinite(prevUE.rsrp) ? prevUE.rsrp : null;
                                const nextRSRP = Number.isFinite(nextUE.rsrp) ? nextUE.rsrp : null;
                                const rsrpDelta = (prevRSRP !== null && nextRSRP !== null) ? (nextRSRP - prevRSRP) : null;

                                newHandovers.push({
                                    sessionId: sessionId,
                                    retryNumber: currentRetry || 1,
                                    timestamp: Date.now(),
                                    time: new Date().toLocaleTimeString(),
                                    ue: nextUE.name || nextUE.supi,
                                    from: prevUE.cell_id_hex,
                                    to: nextUE.cell_id_hex,
                                    method: method,
                                    confidence: typeof confidence === 'number' ? confidence.toFixed(2) : confidence,
                                    rsrp: nextRSRP,
                                    rsrpPrev: prevRSRP,
                                    rsrpDelta: rsrpDelta !== null ? rsrpDelta.toFixed(1) : null,
                                    sinr: Number.isFinite(nextUE.sinr) ? nextUE.sinr : null,
                                    fromBackend: !!backendMatch,
                                });
                            }
                            prevUEsRef.current[nextUE.supi] = { ...nextUE };
                        });
                    } else {
                        movingUEs.forEach(nextUE => {
                            prevUEsRef.current[nextUE.supi] = { ...nextUE };
                        });
                    }

                    if (newHandovers.length > 0) {
                        newHandovers.forEach(h => {
                            addHandover(h);
                            const stats = JSON.parse(localStorage.getItem('kinisis_analytics') || '{"ml":0,"a3":0}');
                            if (h.method === 'ML') stats.ml++;
                            else stats.a3++;
                            localStorage.setItem('kinisis_analytics', JSON.stringify(stats));
                        });
                    }

                    // Update UE positions on map
                    if (movingUEs.length > 0) {
                        setUEs(prev => {
                            const updated = [...prev];
                            movingUEs.forEach(mue => {
                                const idx = updated.findIndex(u => u.supi === mue.supi);
                                if (idx >= 0) {
                                    updated[idx] = { ...updated[idx], ...mue };
                                }
                            });
                            return updated;
                        });
                    }
                } catch (error) {
                    console.error('Error polling UEs:', error);
                }
            }, 1000);
        } else {
            if (pollIntervalRef.current) {
                clearInterval(pollIntervalRef.current);
            }
        }

        return () => {
            if (pollIntervalRef.current) {
                clearInterval(pollIntervalRef.current);
            }
        };
    }, [isRunning, sessionId, mlMode, currentRetry, handoverWsConnected]);

    // Poll ML state (signal quality) for selected UE
    useEffect(() => {
        if (signalPollRef.current) {
            clearInterval(signalPollRef.current);
            signalPollRef.current = null;
        }

        if (!selectedUE?.supi) {
            setSelectedSignalData(null);
            return undefined;
        }

        let cancelled = false;

        const fetchSignalData = async () => {
            try {
                const res = await getUEState(selectedUE.supi);
                if (!cancelled) {
                    setSelectedSignalData(res.data || null);
                }
            } catch (error) {
                if (!cancelled) {
                    setSelectedSignalData(null);
                }
            }
        };

        fetchSignalData();

        if (isRunning || isRetrying) {
            signalPollRef.current = setInterval(fetchSignalData, 1000);
        }

        return () => {
            cancelled = true;
            if (signalPollRef.current) {
                clearInterval(signalPollRef.current);
                signalPollRef.current = null;
            }
        };
    }, [selectedUE?.supi, isRunning, isRetrying]);

    // Handover WebSocket streaming
    useEffect(() => {
        if (!isRunning) {
            if (handoverWsRef.current) {
                handoverWsRef.current.close();
                handoverWsRef.current = null;
            }
            setHandoverWsConnected(false);
            setHandoverWsStatus('disconnected');
            return;
        }

        const buildWsUrl = () => {
            const apiBase = import.meta.env.VITE_API_URL || '/api/v1';
            if (apiBase.startsWith('http')) {
                return apiBase.replace(/^http/, 'ws');
            }
            const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
            const basePath = apiBase.startsWith('/') ? apiBase : `/${apiBase}`;
            return `${wsProtocol}://${window.location.host}${basePath}`;
        };

        const connect = () => {
            if (handoverWsRef.current) {
                handoverWsRef.current.close();
                handoverWsRef.current = null;
            }

            const token = localStorage.getItem('access_token');
            const wsBase = buildWsUrl();
            const wsUrl = `${wsBase}/ue_movement/ws/handovers?limit=50${token ? `&token=${encodeURIComponent(token)}` : ''}`;
            const ws = new WebSocket(wsUrl);
            handoverWsRef.current = ws;
            setHandoverWsStatus('connecting');

            ws.onopen = () => {
                handoverReconnectAttemptRef.current = 0;
                setHandoverWsConnected(true);
                setHandoverWsStatus('connected');
            };

            ws.onclose = () => {
                setHandoverWsConnected(false);
                setHandoverWsStatus('disconnected');
                const attempt = handoverReconnectAttemptRef.current + 1;
                handoverReconnectAttemptRef.current = attempt;
                const backoffMs = Math.min(30000, 1000 * (2 ** (attempt - 1)));
                if (handoverReconnectTimeoutRef.current) {
                    clearTimeout(handoverReconnectTimeoutRef.current);
                }
                handoverReconnectTimeoutRef.current = setTimeout(connect, backoffMs);
            };

            ws.onerror = () => {
                setHandoverWsConnected(false);
                setHandoverWsStatus('disconnected');
            };

            ws.onmessage = (event) => {
                try {
                    const payload = JSON.parse(event.data || '{}');
                    const ue = payload.ue;
                    const eventTime = payload.time;
                    if (!ue || !eventTime) {
                        return;
                    }
                    const key = `${ue}-${eventTime}`;
                    if (processedBackendIdsRef.current.has(key)) {
                        return;
                    }
                    processedBackendIdsRef.current.add(key);

                    const timestamp = Number(eventTime) * 1000;
                    const timeLabel = Number.isFinite(timestamp) ? new Date(timestamp).toLocaleTimeString() : new Date().toLocaleTimeString();

                    const handover = {
                        sessionId: sessionId,
                        retryNumber: currentRetry || 1,
                        timestamp: Number.isFinite(timestamp) ? timestamp : Date.now(),
                        time: timeLabel,
                        ue: ue,
                        from: payload.from,
                        to: payload.to,
                        method: payload.method || 'A3 Event',
                        confidence: typeof payload.confidence === 'number' ? payload.confidence.toFixed(2) : payload.confidence,
                        rsrp: payload.rsrp ?? null,
                        rsrpPrev: null,
                        rsrpDelta: null,
                        sinr: payload.sinr ?? null,
                        fromBackend: true,
                    };

                    addHandover(handover);
                    const stats = JSON.parse(localStorage.getItem('kinisis_analytics') || '{"ml":0,"a3":0}');
                    if (handover.method === 'ML') stats.ml++;
                    else stats.a3++;
                    localStorage.setItem('kinisis_analytics', JSON.stringify(stats));
                } catch (err) {
                    console.warn('Failed to parse handover WebSocket payload:', err);
                }
            };
        };

        connect();

        return () => {
            if (handoverReconnectTimeoutRef.current) {
                clearTimeout(handoverReconnectTimeoutRef.current);
                handoverReconnectTimeoutRef.current = null;
            }
            if (handoverWsRef.current) {
                handoverWsRef.current.close();
                handoverWsRef.current = null;
            }
        };
    }, [isRunning, sessionId, currentRetry]);

    // Timer countdown
    useEffect(() => {
        if (isRunning && timeRemaining > 0) {
            timerIntervalRef.current = setInterval(() => {
                setTimeRemaining(prev => {
                    if (prev <= 1) {
                        handleStop();
                        return 0;
                    }
                    return prev - 1;
                });
            }, 1000);
        }

        return () => {
            if (timerIntervalRef.current) {
                clearInterval(timerIntervalRef.current);
            }
        };
    }, [isRunning, timeRemaining]);

    const handleStart = async () => {
        try {
            prevUEsRef.current = {};
            processedBackendIdsRef.current = new Set();
            await startAllUEs();
            setIsRunning(true);
            setTimeRemaining(duration);
            // Auto-select first UE for Real-Time Metrics if none selected
            if (!selectedUE && ues.length > 0) {
                setSelectedUE(ues[0]);
            }
        } catch (error) {
            console.error('Error starting:', error);
        }
    };

    const handleStop = async () => {
        try {
            await stopAllUEs();
            setIsRunning(false);
            setTimeRemaining(0);
            if (timerIntervalRef.current) {
                clearInterval(timerIntervalRef.current);
            }

            // Reset scenario to ground-truth positions after run ends
            if (scenarioName) {
                await importScenario({ name: scenarioName });
            }
            const uesRes = await getUEs();
            setUEs(uesRes.data || []);
            setSelectedSignalData(null);
        } catch (error) {
            console.error('Error stopping:', error);
        }
    };

    const handleModeChange = async (newMode) => {
        if (isRunning || isRetrying) {
            alert('Cannot change mode during experiment. Stop current experiment first.');
            return;
        }
        try {
            await setMode(newMode);
            setMlMode(newMode);
        } catch (error) {
            console.error('Error setting mode:', error);
        }
    };

    // Retry system functions - using context
    const handleStartRetries = async (numRetries) => {
        setShowRetryModal(false);
        await startRetries(numRetries);
        // Refresh UE list after retries complete
        const uesRes = await getUEs();
        setUEs(uesRes.data || []);
    };

    const handleStopRetries = async () => {
        await stopRetries();
        // Refresh UE list
        const uesRes = await getUEs();
        setUEs(uesRes.data || []);
    };

    const handleClearAll = () => {
        clearAll();
    };

    const center = cells.length > 0
        ? [cells[0].latitude, cells[0].longitude]
        : [37.997, 23.817];

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between">
                <h1 className="text-2xl font-bold">📍 Network Map</h1>
                <div className="flex items-center gap-2 text-xs text-gray-500">
                    <span className={`w-2 h-2 rounded-full ${handoverWsStatus === 'connected' ? 'bg-green-500' : handoverWsStatus === 'connecting' ? 'bg-yellow-500 animate-pulse' : 'bg-red-500'}`}></span>
                    <span>Handover feed: {handoverWsStatus}</span>
                </div>
            </div>

            {/* Experiment Controls */}
            <div className="card">
                <div className="card-body">
                    <div className="flex flex-wrap items-stretch gap-4">
                        {/* Mode Toggle */}
                        <ModeToggle
                            mode={mlMode}
                            onModeChange={handleModeChange}
                            disabled={isRunning || isRetrying}
                        />

                        {/* Center Controls Column */}
                        <div className="flex flex-col gap-3 justify-center min-w-[240px]">
                            {/* Standard Controls */}
                            <div className="flex items-center justify-center gap-2">
                                {/* Duration Input */}
                                <div className="flex flex-col items-center">
                                    <label className="text-[10px] text-gray-500 uppercase tracking-widest font-semibold mb-0.5">Duration</label>
                                    <div className="flex items-center">
                                        <input
                                            type="number"
                                            min="10"
                                            max="300"
                                            value={duration}
                                            onChange={(e) => setDuration(parseInt(e.target.value) || 60)}
                                            disabled={isRunning || isRetrying}
                                            className="w-16 px-2 py-1 border rounded text-center text-sm"
                                        />
                                        <span className="text-xs text-gray-500 ml-1">sec</span>
                                    </div>
                                </div>

                                {/* Start/Stop Button */}
                                {!isRetrying && (
                                    <button
                                        onClick={isRunning ? handleStop : handleStart}
                                        className={`btn ${isRunning ? 'btn-danger' : 'btn-primary'} h-full px-6 flex items-center gap-2 mt-4`}
                                    >
                                        <span className="text-xl">{isRunning ? '⏹️' : '▶️'}</span>
                                        <span className="font-bold">{isRunning ? 'Stop' : 'Start'}</span>
                                    </button>
                                )}
                            </div>

                            {/* Timer Display */}
                            {(isRunning || timeRemaining > 0) && (
                                <div className="bg-blue-50 text-blue-700 px-3 py-1 rounded text-center text-sm font-mono border border-blue-100">
                                    ⏱️ {Math.floor(timeRemaining / 60)}:{(timeRemaining % 60).toString().padStart(2, '0')} remaining
                                </div>
                            )}

                            {/* Run Retries Button */}
                            <button
                                onClick={() => setShowRetryModal(true)}
                                disabled={isRunning || isRetrying}
                                className="btn btn-outline btn-sm w-full flex items-center justify-center gap-2"
                                title="Run multiple automated retries for statistical validation"
                            >
                                <span>🔁</span>
                                <span>Run Retries</span>
                            </button>
                        </div>

                        {/* Signal Panel */}
                        <SignalPanel ue={selectedUE} signalData={selectedSignalData} />
                    </div>
                </div>
            </div>


            {/* Retry Modal / Progress Bar */}
            <RetryModal
                isOpen={showRetryModal}
                onClose={() => setShowRetryModal(false)}
                onStart={handleStartRetries}
                onStop={handleStopRetries}
                currentMode={mlMode}
                scenarioName={scenarioName}
                isRunning={isRetrying}
                currentRetry={currentRetry}
                totalRetries={totalRetries}
            />

            {/* Map */}
            <div className="card">
                <div className="card-body p-0">
                    <div className="h-[500px] rounded-lg overflow-hidden">
                        <MapContainer
                            center={center}
                            zoom={15}
                            style={{ height: '100%', width: '100%' }}
                        >
                            <TileLayer
                                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                                attribution='&copy; OpenStreetMap contributors'
                            />

                            {/* Cells */}
                            {cells.map(cell => (
                                <Circle
                                    key={cell.id}
                                    center={[cell.latitude, cell.longitude]}
                                    radius={cell.radius || 100}
                                    pathOptions={{
                                        color: '#3b82f6',
                                        fillColor: '#3b82f680',
                                        fillOpacity: 0.2,
                                    }}
                                >
                                    <Popup>
                                        <div>
                                            <strong>{cell.name}</strong><br />
                                            Cell ID: {cell.cell_id}<br />
                                            Radius: {cell.radius}m
                                        </div>
                                    </Popup>
                                </Circle>
                            ))}

                            {/* Paths */}
                            {paths.map((path, i) => (
                                <Polyline
                                    key={i}
                                    positions={path.points?.map(p => [p.latitude, p.longitude]) || []}
                                    pathOptions={{
                                        color: path.color || '#6b7280',
                                        weight: 2,
                                        dashArray: '5, 5',
                                    }}
                                />
                            ))}

                            {/* UEs */}
                            {ues.map(ue => {
                                const isSelected = selectedUE?.supi === ue.supi;
                                const connectedCell = isSelected
                                    ? (selectedSignalData?.connected_to || selectedSignalData?.serving_cell || ue.cell_id_hex)
                                    : ue.cell_id_hex;
                                // Nearest cell from neighbor RSRP (strongest signal)
                                const nearestCell = isSelected && selectedSignalData?.neighbor_rsrp_dbm
                                    ? Object.entries(selectedSignalData.neighbor_rsrp_dbm)
                                        .sort((a, b) => b[1] - a[1])[0]?.[0]
                                    : null;

                                return (
                                <Marker
                                    key={ue.supi}
                                    position={[ue.latitude || 0, ue.longitude || 0]}
                                    eventHandlers={{
                                        click: () => setSelectedUE(ue),
                                    }}
                                >
                                    <Popup>
                                        <div>
                                            <strong>{ue.name}</strong><br />
                                            SUPI: {ue.supi}<br />
                                            <span className="text-green-600">Connected: {connectedCell || 'N/A'}</span><br />
                                            {nearestCell && nearestCell !== connectedCell && (
                                                <><span className="text-orange-500">Nearest: {nearestCell}</span><br /></>
                                            )}
                                            Speed: {ue.speed || 'LOW'}
                                            <div className="mt-2 flex gap-1">
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
                                );
                            })}
                        </MapContainer>
                    </div>
                </div>
            </div>

            {/* Handover History */}
            <HandoverHistory
                history={handoverHistory}
                onClear={() => setShowClearModal(true)}
            />

            {/* Real-Time Metrics */}
            <RealTimeMetrics isRunning={isRunning || isRetrying} selectedUE={selectedUE?.supi} />

            {/* Retry Modal */}


            {/* Clear Confirm Modal */}
            <ClearConfirmModal
                isOpen={showClearModal}
                onClose={() => setShowClearModal(false)}
                onConfirm={handleClearAll}
                eventCount={handoverHistory.length}
            />
        </div>
    );
}
