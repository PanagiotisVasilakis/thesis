export default function SignalPanel({ ue, signalData }) {
    if (!ue) {
        return (
            <div className="card flex-1">
                <div className="card-header bg-gray-100 text-gray-900 font-bold text-lg">
                    📡 UE Signal Quality
                </div>
                <div className="card-body text-center text-gray-500 py-8">
                    <span className="text-4xl">📱</span>
                    <p className="mt-2">Click a UE on the map to view signal</p>
                </div>
            </div>
        );
    }

    const rsrps = signalData?.neighbor_rsrp_dbm || {};
    const sinrs = signalData?.neighbor_sinrs || {};
    const loads = signalData?.neighbor_cell_loads || {};
    const connectedTo = signalData?.connected_to;

    const getBarColor = (rsrp) => {
        if (rsrp > -70) return 'bg-green-500';
        if (rsrp > -90) return 'bg-yellow-500';
        return 'bg-red-500';
    };

    const getBarWidth = (rsrp) => {
        return Math.max(0, Math.min(100, (rsrp + 120) * 1.5));
    };

    // Determine nearest cell (strongest RSRP)
    const nearestCell = Object.keys(rsrps).length > 0
        ? Object.entries(rsrps).sort((a, b) => b[1] - a[1])[0]?.[0]
        : null;
    const handoverPending = nearestCell && nearestCell !== connectedTo;

    return (
        <div className="card flex-1">
            <div className="card-header bg-gray-100 text-gray-900 font-bold text-lg flex justify-between items-center">
                <span>📡 UE Signal Quality</span>
                <span className="badge bg-cyan-600 text-white">{ue.name}</span>
            </div>
            <div className="card-body">
                <div className="mb-3 flex flex-wrap items-center gap-3">
                    <div>
                        <span className="text-sm text-gray-600">Connected to: </span>
                        <span className="badge badge-success">{connectedTo || 'None'}</span>
                    </div>
                    {nearestCell && (
                        <div>
                            <span className="text-sm text-gray-600">Nearest: </span>
                            <span className={`badge ${handoverPending ? 'bg-orange-500 text-white' : 'bg-gray-200'}`}>
                                {nearestCell}
                            </span>
                        </div>
                    )}
                    {handoverPending && (
                        <span className="text-xs text-orange-600 animate-pulse">⚡ Handover candidate</span>
                    )}
                </div>

                <table className="w-full text-sm">
                    <thead>
                        <tr className="text-gray-500 border-b">
                            <th className="text-left py-1">Cell</th>
                            <th className="text-left py-1">RSRP (dBm)</th>
                            <th className="text-left py-1">SINR</th>
                            <th className="text-left py-1">Load</th>
                        </tr>
                    </thead>
                    <tbody>
                        {Object.entries(rsrps).map(([cellId, rsrp]) => (
                            <tr key={cellId} className={cellId === connectedTo ? 'bg-green-50' : ''}>
                                <td className="py-1">
                                    {cellId} {cellId === connectedTo && '✓'}
                                </td>
                                <td className="py-1">
                                    <div className="flex items-center gap-2">
                                        <div className="w-20 h-3 bg-gray-200 rounded">
                                            <div
                                                className={`h-full rounded ${getBarColor(rsrp)}`}
                                                style={{ width: `${getBarWidth(rsrp)}%` }}
                                            />
                                        </div>
                                        <span>{rsrp.toFixed(1)}</span>
                                    </div>
                                </td>
                                <td className="py-1">{sinrs[cellId]?.toFixed(1) || 'N/A'}</td>
                                <td className="py-1">
                                    <span className="badge bg-gray-200">{loads[cellId] || 0}</span>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>

                {signalData?.observed_qos && (
                    <div className="mt-3 pt-3 border-t text-sm">
                        <strong>QoS:</strong> Latency {signalData.observed_qos.latency_ms?.toFixed(1)}ms |
                        Throughput {signalData.observed_qos.throughput_mbps?.toFixed(1)} Mbps
                    </div>
                )}
            </div>
        </div>
    );
}
