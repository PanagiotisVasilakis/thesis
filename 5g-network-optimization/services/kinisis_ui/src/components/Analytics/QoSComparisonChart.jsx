import { useMemo } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine } from 'recharts';

export default function QoSComparisonChart({ history }) {
    // Group by method and calculate averages
    const chartData = useMemo(() => {
        if (!history || history.length === 0) return [];

        // Sort by timestamp
        const sorted = [...history].sort((a, b) =>
            (a.timestamp || 0) - (b.timestamp || 0)
        );

        // Create time-series data points
        const data = sorted.map((h, i) => ({
            index: i + 1,
            time: h.time,
            rsrp: h.rsrp || -90,
            sinr: h.sinr || 10,
            method: h.method,
            isML: h.method === 'ML',
        }));

        return data;
    }, [history]);

    // Calculate summary statistics
    const stats = useMemo(() => {
        const mlEvents = history.filter(h => h.method === 'ML');
        const a3Events = history.filter(h => h.method === 'A3 Event');

        const calcMean = arr => arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0;

        return {
            ml: {
                count: mlEvents.length,
                avgRsrp: calcMean(mlEvents.map(h => h.rsrp || -90)).toFixed(1),
                avgSinr: calcMean(mlEvents.map(h => h.sinr || 10)).toFixed(1),
            },
            a3: {
                count: a3Events.length,
                avgRsrp: calcMean(a3Events.map(h => h.rsrp || -90)).toFixed(1),
                avgSinr: calcMean(a3Events.map(h => h.sinr || 10)).toFixed(1),
            },
        };
    }, [history]);

    if (history.length === 0) {
        return (
            <div className="card">
                <div className="card-header">📶 QoS Comparison</div>
                <div className="card-body text-center text-gray-500 py-8">
                    Run experiments to see QoS comparison data
                </div>
            </div>
        );
    }

    return (
        <div className="card">
            <div className="card-header">📶 QoS Comparison: ML vs A3</div>
            <div className="card-body">
                {/* Summary Stats */}
                <div className="grid grid-cols-2 gap-4 mb-4">
                    <div className="bg-green-50 rounded-lg p-3">
                        <div className="text-sm font-medium text-green-800">ML Mode</div>
                        <div className="text-xs text-green-600 mt-1">
                            {stats.ml.count} events | Avg RSRP: {stats.ml.avgRsrp} dBm | Avg SINR: {stats.ml.avgSinr} dB
                        </div>
                    </div>
                    <div className="bg-yellow-50 rounded-lg p-3">
                        <div className="text-sm font-medium text-yellow-800">A3 Mode</div>
                        <div className="text-xs text-yellow-600 mt-1">
                            {stats.a3.count} events | Avg RSRP: {stats.a3.avgRsrp} dBm | Avg SINR: {stats.a3.avgSinr} dB
                        </div>
                    </div>
                </div>

                {/* RSRP Chart */}
                <div className="mb-4">
                    <h4 className="text-sm font-medium mb-2">RSRP Over Time</h4>
                    <div className="h-48">
                        <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={chartData}>
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis dataKey="index" label={{ value: 'Handover #', position: 'bottom' }} />
                                <YAxis
                                    domain={[-110, -70]}
                                    label={{ value: 'RSRP (dBm)', angle: -90, position: 'insideLeft' }}
                                />
                                <Tooltip
                                    formatter={(value, name) => [`${value} dBm`, name]}
                                    labelFormatter={(label) => `Handover #${label}`}
                                />
                                <ReferenceLine y={-100} stroke="red" strokeDasharray="5 5" label="Min acceptable" />
                                <Line
                                    type="monotone"
                                    dataKey="rsrp"
                                    stroke="#3b82f6"
                                    dot={(props) => {
                                        const { cx, cy, payload } = props;
                                        return (
                                            <circle
                                                cx={cx}
                                                cy={cy}
                                                r={4}
                                                fill={payload.isML ? '#22c55e' : '#f59e0b'}
                                            />
                                        );
                                    }}
                                />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>
                </div>

                {/* SINR Chart */}
                <div>
                    <h4 className="text-sm font-medium mb-2">SINR Over Time</h4>
                    <div className="h-48">
                        <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={chartData}>
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis dataKey="index" label={{ value: 'Handover #', position: 'bottom' }} />
                                <YAxis
                                    domain={[0, 25]}
                                    label={{ value: 'SINR (dB)', angle: -90, position: 'insideLeft' }}
                                />
                                <Tooltip
                                    formatter={(value, name) => [`${value} dB`, name]}
                                    labelFormatter={(label) => `Handover #${label}`}
                                />
                                <ReferenceLine y={5} stroke="red" strokeDasharray="5 5" label="Min acceptable" />
                                <Line
                                    type="monotone"
                                    dataKey="sinr"
                                    stroke="#8b5cf6"
                                    dot={(props) => {
                                        const { cx, cy, payload } = props;
                                        return (
                                            <circle
                                                cx={cx}
                                                cy={cy}
                                                r={4}
                                                fill={payload.isML ? '#22c55e' : '#f59e0b'}
                                            />
                                        );
                                    }}
                                />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>
                </div>

                {/* Legend */}
                <div className="flex justify-center gap-6 mt-4 text-sm">
                    <div className="flex items-center gap-2">
                        <div className="w-3 h-3 rounded-full bg-green-500"></div>
                        <span>ML Handover</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <div className="w-3 h-3 rounded-full bg-yellow-500"></div>
                        <span>A3 Handover</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <div className="w-8 border-t-2 border-dashed border-red-500"></div>
                        <span>Min Threshold</span>
                    </div>
                </div>
            </div>
        </div>
    );
}
