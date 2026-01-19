import { useState, useEffect, useRef } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, ResponsiveContainer, ReferenceLine } from 'recharts';
import { getLiveMetrics } from '../../api/nefClient';

export default function RealTimeMetrics({ isRunning, selectedUE }) {
    const [metrics, setMetrics] = useState([]);
    const [latestMetrics, setLatestMetrics] = useState(null);
    const [apiLatencyMs, setApiLatencyMs] = useState(null);
    const [apiTransport, setApiTransport] = useState(null);
    const [useWebSocket, setUseWebSocket] = useState(true);
    const intervalRef = useRef(null);
    const latencySamplesRef = useRef([]);
    const wsRef = useRef(null);
    const wsReconnectTimeoutRef = useRef(null);
    const wsReconnectAttemptRef = useRef(0);
    const maxDataPoints = 60; // Keep last 60 seconds

    useEffect(() => {
        setMetrics([]);
        setLatestMetrics(null);
        latencySamplesRef.current = [];
        setApiLatencyMs(null);
        setApiTransport(null);
        setUseWebSocket(true);
        wsReconnectAttemptRef.current = 0;
        if (wsReconnectTimeoutRef.current) {
            clearTimeout(wsReconnectTimeoutRef.current);
            wsReconnectTimeoutRef.current = null;
        }
    }, [selectedUE]);

    useEffect(() => {
        if (!isRunning || !selectedUE) {
            if (intervalRef.current) {
                clearInterval(intervalRef.current);
            }
            if (wsRef.current) {
                wsRef.current.close();
                wsRef.current = null;
            }
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

        if (useWebSocket) {
            const token = localStorage.getItem('access_token');
            const wsBase = buildWsUrl();
            const wsUrl = `${wsBase}/ue_movement/ws/ue-metrics?supi=${encodeURIComponent(selectedUE)}${token ? `&token=${encodeURIComponent(token)}` : ''}`;
            const ws = new WebSocket(wsUrl);
            wsRef.current = ws;
            setApiTransport('ws');
            setApiLatencyMs(null);

            ws.onmessage = (event) => {
                const now = new Date();
                const timeLabel = now.toLocaleTimeString().split(' ')[0];
                try {
                    const data = JSON.parse(event.data || '{}');
                    const qos = data.qos || {};

                    const newMetric = {
                        time: timeLabel,
                        timestamp: Date.now(),
                        rsrp: Number.isFinite(data.rsrp) ? data.rsrp : null,
                        sinr: Number.isFinite(data.sinr) ? data.sinr : null,
                        throughput: Number.isFinite(qos.throughput_mbps) ? qos.throughput_mbps : null,
                        latency: Number.isFinite(qos.latency_ms) ? qos.latency_ms : null,
                        handoverPending: false,
                        predictedCell: null,
                        confidence: null,
                        servingCell: data.serving_cell || null,
                    };

                    setLatestMetrics(newMetric);

                    if (Number.isFinite(newMetric.rsrp) && Number.isFinite(newMetric.sinr)) {
                        setMetrics(prev => {
                            const updated = [...prev, newMetric];
                            return updated.slice(-maxDataPoints);
                        });
                    }
                } catch (err) {
                    console.warn('Failed to parse WebSocket metrics payload:', err);
                }
            };

            ws.onerror = () => {
                setApiTransport('ws');
            };

            ws.onclose = () => {
                const attempt = wsReconnectAttemptRef.current + 1;
                wsReconnectAttemptRef.current = attempt;
                const maxAttempts = 5;
                if (attempt > maxAttempts) {
                    setUseWebSocket(false);
                    return;
                }
                const backoffMs = Math.min(30000, 1000 * (2 ** (attempt - 1)));
                if (wsReconnectTimeoutRef.current) {
                    clearTimeout(wsReconnectTimeoutRef.current);
                }
                wsReconnectTimeoutRef.current = setTimeout(() => {
                    if (useWebSocket) {
                        setUseWebSocket(true);
                    }
                }, backoffMs);
            };

            return () => {
                if (wsRef.current) {
                    wsRef.current.close();
                    wsRef.current = null;
                }
                if (wsReconnectTimeoutRef.current) {
                    clearTimeout(wsReconnectTimeoutRef.current);
                    wsReconnectTimeoutRef.current = null;
                }
            };
        }

        setApiTransport('http');
        intervalRef.current = setInterval(async () => {
                const now = new Date();
                const timeLabel = now.toLocaleTimeString().split(' ')[0];
                const requestStart = performance.now();

                try {
                    const res = await getLiveMetrics(selectedUE);
                    const responseTime = performance.now() - requestStart;
                    const samples = latencySamplesRef.current.concat(responseTime).slice(-20);
                    latencySamplesRef.current = samples;
                    const avgLatency = samples.reduce((sum, val) => sum + val, 0) / samples.length;
                    setApiLatencyMs(avgLatency);
                    if (avgLatency > 500) {
                        console.warn(`Live metrics polling latency high: ${avgLatency.toFixed(0)}ms`);
                    }

                    const data = res.data || {};
                    const qos = data.qos || {};

                    const newMetric = {
                        time: timeLabel,
                        timestamp: Date.now(),
                        rsrp: Number.isFinite(data.rsrp) ? data.rsrp : null,
                        sinr: Number.isFinite(data.sinr) ? data.sinr : null,
                        throughput: Number.isFinite(qos.throughput_mbps) ? qos.throughput_mbps : null,
                        latency: Number.isFinite(qos.latency_ms) ? qos.latency_ms : null,
                        handoverPending: false,
                        predictedCell: null,
                        confidence: null,
                        servingCell: data.serving_cell || null,
                    };

                    setLatestMetrics(newMetric);

                    if (Number.isFinite(newMetric.rsrp) && Number.isFinite(newMetric.sinr)) {
                        setMetrics(prev => {
                            const updated = [...prev, newMetric];
                            return updated.slice(-maxDataPoints);
                        });
                    }
                } catch (error) {
                    const responseTime = performance.now() - requestStart;
                    const samples = latencySamplesRef.current.concat(responseTime).slice(-20);
                    latencySamplesRef.current = samples;
                    const avgLatency = samples.reduce((sum, val) => sum + val, 0) / samples.length;
                    setApiLatencyMs(avgLatency);
                    if (avgLatency > 500) {
                        console.warn(`Live metrics polling latency high: ${avgLatency.toFixed(0)}ms`);
                    }
                    setLatestMetrics(null);
                }
            }, 1000);
        return () => {
            if (intervalRef.current) {
                clearInterval(intervalRef.current);
            }
        };
    }, [isRunning, selectedUE, useWebSocket]);

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
                    {apiTransport === 'ws' && (
                        <span className="text-xs text-gray-500">API: WS</span>
                    )}
                    {apiTransport === 'http' && apiLatencyMs !== null && (
                        <span className="text-xs text-gray-500">API: {apiLatencyMs.toFixed(0)}ms</span>
                    )}
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
                                    <div className={`text-xl font-bold ${latestMetrics.rsrp !== null ? getRsrpColor(latestMetrics.rsrp) : 'text-gray-400'}`}>
                                        {latestMetrics.rsrp !== null ? latestMetrics.rsrp.toFixed(1) : '—'}
                                    </div>
                                    <div className="text-xs text-gray-500">RSRP (dBm)</div>
                                </div>
                                <div className="bg-gray-50 rounded p-2 text-center">
                                    <div className={`text-xl font-bold ${latestMetrics.sinr !== null ? getSinrColor(latestMetrics.sinr) : 'text-gray-400'}`}>
                                        {latestMetrics.sinr !== null ? latestMetrics.sinr.toFixed(1) : '—'}
                                    </div>
                                    <div className="text-xs text-gray-500">SINR (dB)</div>
                                </div>
                                <div className="bg-gray-50 rounded p-2 text-center">
                                    <div className="text-xl font-bold text-blue-600">
                                        {latestMetrics.throughput !== null ? latestMetrics.throughput.toFixed(0) : '—'}
                                    </div>
                                    <div className="text-xs text-gray-500">Throughput (Mbps)</div>
                                </div>
                                <div className="bg-gray-50 rounded p-2 text-center">
                                    <div className="text-xl font-bold text-purple-600">
                                        {latestMetrics.latency !== null ? latestMetrics.latency.toFixed(0) : '—'}
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
                                        {latestMetrics.confidence !== null && (
                                            <>| Confidence: {(latestMetrics.confidence * 100).toFixed(0)}%</>
                                        )}
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
