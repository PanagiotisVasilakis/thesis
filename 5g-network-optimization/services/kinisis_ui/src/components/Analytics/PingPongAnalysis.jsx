import { useMemo } from 'react';

export default function PingPongAnalysis({ history }) {
    const analysis = useMemo(() => {
        if (!history || history.length < 2) {
            return { total: 0, pingPong: 0, rate: 0, byUe: {}, byMode: { ML: 0, A3: 0 } };
        }

        // Sort by timestamp
        const sorted = [...history].sort((a, b) =>
            (a.timestamp || 0) - (b.timestamp || 0)
        );

        let pingPongCount = 0;
        const byUe = {};
        const byMode = { ML: 0, A3: 0 };
        const pingPongEvents = [];

        // Check each handover for ping-pong (return to source within 10s)
        for (let i = 1; i < sorted.length; i++) {
            const current = sorted[i];
            const previous = sorted[i - 1];

            // Same UE, returning to previous source cell within 10s
            if (current.ue === previous.ue &&
                current.from === previous.to &&
                current.to === previous.from) {

                const timeDiff = (current.timestamp - previous.timestamp) / 1000;

                if (timeDiff < 10) {
                    pingPongCount++;
                    byUe[current.ue] = (byUe[current.ue] || 0) + 1;

                    // Track by mode (use the mode of the returning handover)
                    const mode = current.method === 'ML' ? 'ML' : 'A3';
                    byMode[mode]++;

                    pingPongEvents.push({
                        ue: current.ue,
                        mode: mode,
                        from: previous.to,
                        to: current.to,
                        timeDiff: timeDiff.toFixed(1)
                    });
                }
            }
        }

        return {
            total: history.length,
            pingPong: pingPongCount,
            rate: history.length > 0 ? (pingPongCount / history.length * 100).toFixed(1) : 0,
            byUe: byUe,
            byMode: byMode,
            events: pingPongEvents,
        };
    }, [history]);

    return (
        <div className="card">
            <div className="card-header">🔄 Ping-Pong Analysis</div>
            <div className="card-body">
                <div className="grid grid-cols-3 gap-4 mb-4">
                    <div className="text-center">
                        <div className="text-3xl font-bold">{analysis.total}</div>
                        <div className="text-sm text-gray-500">Total Handovers</div>
                    </div>
                    <div className="text-center">
                        <div className="text-3xl font-bold text-red-600">{analysis.pingPong}</div>
                        <div className="text-sm text-gray-500">Ping-Pong Events</div>
                    </div>
                    <div className="text-center">
                        <div className="text-3xl font-bold text-orange-600">{analysis.rate}%</div>
                        <div className="text-sm text-gray-500">Ping-Pong Rate</div>
                    </div>
                </div>

                {/* Ping-Pong by Mode */}
                {analysis.pingPong > 0 && (
                    <div className="mb-4 p-3 bg-gray-50 rounded-lg">
                        <h4 className="font-semibold mb-2">By Mode</h4>
                        <div className="grid grid-cols-2 gap-4">
                            <div className="flex items-center gap-2">
                                <span className="badge badge-success">ML</span>
                                <span className="text-red-600 font-bold">{analysis.byMode.ML}</span>
                                <span className="text-gray-500 text-sm">ping-pongs</span>
                            </div>
                            <div className="flex items-center gap-2">
                                <span className="badge badge-warning">A3</span>
                                <span className="text-red-600 font-bold">{analysis.byMode.A3}</span>
                                <span className="text-gray-500 text-sm">ping-pongs</span>
                            </div>
                        </div>
                    </div>
                )}

                {/* Ping-Pong Events Table */}
                {analysis.events && analysis.events.length > 0 && (
                    <div className="mb-4">
                        <h4 className="font-semibold mb-2">Ping-Pong Events</h4>
                        <table className="table table-sm w-full text-sm">
                            <thead className="bg-gray-50">
                                <tr>
                                    <th className="text-left px-2 py-1">UE</th>
                                    <th className="text-left px-2 py-1">Mode</th>
                                    <th className="text-left px-2 py-1">Cells</th>
                                    <th className="text-left px-2 py-1">Time</th>
                                </tr>
                            </thead>
                            <tbody>
                                {analysis.events.map((event, i) => (
                                    <tr key={i} className="border-t">
                                        <td className="px-2 py-1">{event.ue}</td>
                                        <td className="px-2 py-1">
                                            <span className={`badge ${event.mode === 'ML' ? 'badge-success' : 'badge-warning'}`}>
                                                {event.mode}
                                            </span>
                                        </td>
                                        <td className="px-2 py-1 font-mono text-xs">
                                            {event.from} ↔ {event.to}
                                        </td>
                                        <td className="px-2 py-1 text-gray-500">{event.timeDiff}s</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}

                {Object.keys(analysis.byUe).length > 0 && (
                    <div>
                        <h4 className="font-semibold mb-2">Per-UE Breakdown</h4>
                        <table className="table table-sm w-full">
                            <thead>
                                <tr>
                                    <th className="text-left">UE</th>
                                    <th className="text-left">Ping-Pong Count</th>
                                </tr>
                            </thead>
                            <tbody>
                                {Object.entries(analysis.byUe).map(([ue, count]) => (
                                    <tr key={ue} className="border-t">
                                        <td className="py-1">{ue}</td>
                                        <td className="py-1 text-red-600">{count}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}

                {analysis.pingPong === 0 && analysis.total > 0 && (
                    <div className="text-center text-green-600 font-semibold mt-2">
                        ✅ No ping-pong detected!
                    </div>
                )}
            </div>
        </div>
    );
}

