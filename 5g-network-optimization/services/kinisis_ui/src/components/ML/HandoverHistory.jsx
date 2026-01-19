export default function HandoverHistory({ history, onClear }) {
    const exportCSV = () => {
        if (history.length === 0) return;
        const csv = 'Time,Session,Retry,UE,From,To,Method,Confidence,RSRP,SINR\n' +
            history.map(h => `${h.time},${h.sessionId || 'unknown'},${h.retryNumber || 1},${h.ue},${h.from},${h.to},${h.method},${h.confidence ?? ''},${h.rsrp || ''},${h.sinr || ''}`).join('\n');
        const blob = new Blob([csv], { type: 'text/csv' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `handover_history_${Date.now()}.csv`;
        a.click();
    };

    return (
        <div className="card">
            <div className="card-header flex justify-between items-center">
                <span>📋 Handover History ({history.length} events)</span>
                <div className="flex gap-2">
                    <button onClick={exportCSV} className="btn btn-outline text-sm" disabled={history.length === 0}>
                        📥 CSV
                    </button>
                    <button onClick={onClear} className="btn btn-outline text-sm text-red-600 hover:bg-red-50">
                        🗑️ Clear
                    </button>
                </div>
            </div>
            <div className="card-body p-0">
                <div className="max-h-48 overflow-y-auto">
                    <table className="w-full text-sm">
                        <thead className="bg-gray-50 sticky top-0">
                            <tr>
                                <th className="text-left px-3 py-2">Time</th>
                                <th className="text-left px-3 py-2">Retry</th>
                                <th className="text-left px-3 py-2">UE</th>
                                <th className="text-left px-3 py-2">From</th>
                                <th className="text-left px-3 py-2">To</th>
                                <th className="text-left px-3 py-2">Method</th>
                                <th className="text-left px-3 py-2">Conf.</th>
                                <th className="text-left px-3 py-2">RSRP</th>
                                <th className="text-left px-3 py-2">SINR</th>
                            </tr>
                        </thead>
                        <tbody>
                            {history.length === 0 ? (
                                <tr>
                                    <td colSpan={9} className="text-center text-gray-500 py-8">
                                        Handover events will appear here when UEs move...
                                    </td>
                                </tr>
                            ) : (
                                [...history].reverse().map((h, i) => (
                                    <tr key={i} className="border-t hover:bg-gray-50">
                                        <td className="px-3 py-2">{h.time}</td>
                                        <td className="px-3 py-2 text-gray-500">#{h.retryNumber || 1}</td>
                                        <td className="px-3 py-2">{h.ue}</td>
                                        <td className="px-3 py-2 font-mono text-xs">{h.from}</td>
                                        <td className="px-3 py-2 font-mono text-xs">{h.to}</td>
                                        <td className="px-3 py-2">
                                            <span className={`badge ${h.method === 'ML' ? 'badge-success' : 'badge-warning'}`}>
                                                {h.method}
                                            </span>
                                        </td>
                                        <td className="px-3 py-2">{h.confidence ?? '—'}</td>
                                        <td className="px-3 py-2 text-blue-600">{h.rsrp || '-'} dBm</td>
                                        <td className="px-3 py-2 text-green-600">{h.sinr || '-'} dB</td>
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}

