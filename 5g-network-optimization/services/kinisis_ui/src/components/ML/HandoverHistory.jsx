export default function HandoverHistory({ history, onClear }) {
    const exportCSV = () => {
        if (history.length === 0) return;
        const csv = 'Time,UE,From,To,Method,Confidence\n' +
            history.map(h => `${h.time},${h.ue},${h.from},${h.to},${h.method},${h.confidence}`).join('\n');
        const blob = new Blob([csv], { type: 'text/csv' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'handover_history.csv';
        a.click();
    };

    return (
        <div className="card">
            <div className="card-header flex justify-between items-center">
                <span>📋 Handover History</span>
                <div className="flex gap-2">
                    <button onClick={exportCSV} className="btn btn-outline text-sm">
                        📥 CSV
                    </button>
                    <button onClick={onClear} className="btn btn-outline text-sm">
                        🗑️ Clear
                    </button>
                </div>
            </div>
            <div className="card-body p-0">
                <div className="max-h-48 overflow-y-auto">
                    <table className="w-full text-sm">
                        <thead className="bg-gray-50 sticky top-0">
                            <tr>
                                <th className="text-left px-4 py-2">Time</th>
                                <th className="text-left px-4 py-2">UE</th>
                                <th className="text-left px-4 py-2">From</th>
                                <th className="text-left px-4 py-2">To</th>
                                <th className="text-left px-4 py-2">Method</th>
                                <th className="text-left px-4 py-2">Confidence</th>
                            </tr>
                        </thead>
                        <tbody>
                            {history.length === 0 ? (
                                <tr>
                                    <td colSpan={6} className="text-center text-gray-500 py-8">
                                        Handover events will appear here when UEs move...
                                    </td>
                                </tr>
                            ) : (
                                history.map((h, i) => (
                                    <tr key={i} className="border-t">
                                        <td className="px-4 py-2">{h.time}</td>
                                        <td className="px-4 py-2">{h.ue}</td>
                                        <td className="px-4 py-2">{h.from}</td>
                                        <td className="px-4 py-2">{h.to}</td>
                                        <td className="px-4 py-2">
                                            <span className={`badge ${h.method === 'ML' ? 'badge-success' : 'badge-warning'}`}>
                                                {h.method}
                                            </span>
                                        </td>
                                        <td className="px-4 py-2">{h.confidence}</td>
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
