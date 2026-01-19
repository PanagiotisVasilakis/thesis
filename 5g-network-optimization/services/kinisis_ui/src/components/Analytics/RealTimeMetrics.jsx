import { useState, useEffect, useRef } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, ResponsiveContainer, ReferenceLine } from 'recharts';

export default function RealTimeMetrics({ isRunning, selectedUE }) {
    const [metrics, setMetrics] = useState([]);
    const [latestMetrics, setLatestMetrics] = useState(null);
    const intervalRef = useRef(null);
    const maxDataPoints = 60; // Keep last 60 seconds

    useEffect(() => {
        if (isRunning) {
            // Start streaming metrics
            intervalRef.current = setInterval(() => {
                const now = new Date();
                const timeLabel = now.toLocaleTimeString().split(' ')[0];

                // Generate realistic mock metrics
                const newMetric = {
                    time: timeLabel,
                    timestamp: Date.now(),
                    rsrp: -75 + Math.random() * -25 + Math.sin(Date.now() / 5000) * 5,
                    sinr: 12 + Math.random() * 8 + Math.cos(Date.now() / 4000) * 3,
                    throughput: 50 + Math.random() * 100,
                    latency: 10 + Math.random() * 30,
                    handoverPending: Math.random() > 0.95,
                    predictedCell: Math.random() > 0.9 ? 'Cell-B' : null,
                    confidence: 0.8 + Math.random() * 0.2,
                };

                setLatestMetrics(newMetric);
                setMetrics(prev => {
                    const updated = [...prev, newMetric];
                    return updated.slice(-maxDataPoints);
                });
            }, 1000);
        } else {
            if (intervalRef.current) {
                clearInterval(intervalRef.current);
            }
        }

        return () => {
            if (intervalRef.current) {
                clearInterval(intervalRef.current);
            }
        };
    }, [isRunning]);

    const getRsrpColor = (rsrp) => {
        if (rsrp >= -80) return 'text-green-600';
        if (rsrp >= -95) return 'text-yellow-600';
        return 'text-red-600';
    };

    const getSinrColor = (sinr) => {
        if (sinr >= 15) return 'text-green-600';
        if (sinr >= 5) return 'text-yellow-600';
        return 'text-red-600';
    };

    return (
        <div className="card">
            <div className="card-header flex justify-between items-center">
                <span>📡 Real-Time Metrics {selectedUE && `(${selectedUE})`}</span>
                <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${isRunning ? 'bg-green-500 animate-pulse' : 'bg-gray-300'}`}></span>
                    <span className="text-xs text-gray-500">
                        {isRunning ? 'Streaming' : 'Stopped'}
                    </span>
                </div>
            </div>
            <div className="card-body">
                {!isRunning && metrics.length === 0 ? (
                    <div className="text-center text-gray-500 py-8">
                        Start UE movement to see real-time metrics
                    </div>
                ) : (
                    <>
                        {/* Live Metrics Cards */}
                        {latestMetrics && (
                            <div className="grid grid-cols-4 gap-2 mb-4">
                                <div className="bg-gray-50 rounded p-2 text-center">
                                    <div className={`text-xl font-bold ${getRsrpColor(latestMetrics.rsrp)}`}>
                                        {latestMetrics.rsrp.toFixed(1)}
                                    </div>
                                    <div className="text-xs text-gray-500">RSRP (dBm)</div>
                                </div>
                                <div className="bg-gray-50 rounded p-2 text-center">
                                    <div className={`text-xl font-bold ${getSinrColor(latestMetrics.sinr)}`}>
                                        {latestMetrics.sinr.toFixed(1)}
                                    </div>
                                    <div className="text-xs text-gray-500">SINR (dB)</div>
                                </div>
                                <div className="bg-gray-50 rounded p-2 text-center">
                                    <div className="text-xl font-bold text-blue-600">
                                        {latestMetrics.throughput.toFixed(0)}
                                    </div>
                                    <div className="text-xs text-gray-500">Throughput (Mbps)</div>
                                </div>
                                <div className="bg-gray-50 rounded p-2 text-center">
                                    <div className="text-xl font-bold text-purple-600">
                                        {latestMetrics.latency.toFixed(0)}
                                    </div>
                                    <div className="text-xs text-gray-500">Latency (ms)</div>
                                </div>
                            </div>
                        )}

                        {/* Handover Prediction Alert */}
                        {latestMetrics?.handoverPending && (
                            <div className="bg-orange-100 border border-orange-300 rounded-lg p-2 mb-4 flex items-center gap-2">
                                <span className="animate-pulse">🔄</span>
                                <div>
                                    <div className="font-medium text-orange-800">Handover Predicted</div>
                                    <div className="text-xs text-orange-600">
                                        Target: {latestMetrics.predictedCell || 'Evaluating...'}
                                        | Confidence: {(latestMetrics.confidence * 100).toFixed(0)}%
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* RSRP Chart */}
                        <div className="mb-4">
                            <div className="text-xs font-medium text-gray-500 mb-1">RSRP Over Time</div>
                            <div className="h-32">
                                <ResponsiveContainer width="100%" height="100%">
                                    <LineChart data={metrics}>
                                        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                                        <XAxis
                                            dataKey="time"
                                            tick={{ fontSize: 10 }}
                                            interval="preserveStartEnd"
                                        />
                                        <YAxis
                                            domain={[-110, -60]}
                                            tick={{ fontSize: 10 }}
                                            width={40}
                                        />
                                        <ReferenceLine y={-100} stroke="#ef4444" strokeDasharray="5 5" />
                                        <Line
                                            type="monotone"
                                            dataKey="rsrp"
                                            stroke="#3b82f6"
                                            dot={false}
                                            strokeWidth={2}
                                            isAnimationActive={false}
                                        />
                                    </LineChart>
                                </ResponsiveContainer>
                            </div>
                        </div>

                        {/* SINR Chart */}
                        <div>
                            <div className="text-xs font-medium text-gray-500 mb-1">SINR Over Time</div>
                            <div className="h-32">
                                <ResponsiveContainer width="100%" height="100%">
                                    <LineChart data={metrics}>
                                        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                                        <XAxis
                                            dataKey="time"
                                            tick={{ fontSize: 10 }}
                                            interval="preserveStartEnd"
                                        />
                                        <YAxis
                                            domain={[0, 25]}
                                            tick={{ fontSize: 10 }}
                                            width={40}
                                        />
                                        <ReferenceLine y={5} stroke="#ef4444" strokeDasharray="5 5" />
                                        <Line
                                            type="monotone"
                                            dataKey="sinr"
                                            stroke="#8b5cf6"
                                            dot={false}
                                            strokeWidth={2}
                                            isAnimationActive={false}
                                        />
                                    </LineChart>
                                </ResponsiveContainer>
                            </div>
                        </div>

                        {/* Legend */}
                        <div className="flex justify-center gap-4 mt-3 text-xs text-gray-500">
                            <div className="flex items-center gap-1">
                                <div className="w-6 border-t-2 border-dashed border-red-500"></div>
                                <span>Min Threshold</span>
                            </div>
                            <div className="flex items-center gap-1">
                                <div className="w-3 h-0.5 bg-blue-500"></div>
                                <span>RSRP</span>
                            </div>
                            <div className="flex items-center gap-1">
                                <div className="w-3 h-0.5 bg-purple-500"></div>
                                <span>SINR</span>
                            </div>
                        </div>
                    </>
                )}
            </div>
        </div>
    );
}
