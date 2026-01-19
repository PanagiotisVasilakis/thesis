import { useMemo } from 'react';

/**
 * UE Type Breakdown Component
 * Analyzes handover statistics by UE category: Car, Pedestrian, Cyclist, Drone, IoT-Sensor
 */

// UE category definitions
const UE_CATEGORIES = {
    'Car': {
        pattern: /^Car/i,
        icon: '🚗',
        color: 'bg-blue-100 text-blue-800',
        description: 'High-speed vehicular'
    },
    'Pedestrian': {
        pattern: /^Pedestrian/i,
        icon: '🚶',
        color: 'bg-green-100 text-green-800',
        description: 'Low-speed walking'
    },
    'Cyclist': {
        pattern: /^Cyclist/i,
        icon: '🚴',
        color: 'bg-yellow-100 text-yellow-800',
        description: 'Medium-speed cycling'
    },
    'Drone': {
        pattern: /^Drone/i,
        icon: '🛸',
        color: 'bg-purple-100 text-purple-800',
        description: 'High mobility aerial'
    },
    'IoT-Sensor': {
        pattern: /^IoT/i,
        icon: '📡',
        color: 'bg-gray-100 text-gray-800',
        description: 'Stationary/low mobility'
    }
};

// Categorize a UE name
function categorizeUE(ueName) {
    for (const [category, config] of Object.entries(UE_CATEGORIES)) {
        if (config.pattern.test(ueName)) {
            return category;
        }
    }
    return 'Other';
}

export default function UETypeBreakdown({ history }) {
    const analysis = useMemo(() => {
        if (!history || history.length === 0) {
            return { categories: {}, hasData: false };
        }

        // Initialize category stats
        const categories = {};
        for (const category of Object.keys(UE_CATEGORIES)) {
            categories[category] = {
                ...UE_CATEGORIES[category],
                name: category,
                total: 0,
                ml: 0,
                a3: 0,
                avgRSRP: 0,
                avgSINR: 0,
                rsrpSum: 0,
                sinrSum: 0,
                pingPongs: 0,
                ues: new Set()
            };
        }

        // Categorize each handover
        history.forEach(h => {
            const category = categorizeUE(h.ue);
            if (!categories[category]) return;

            categories[category].total++;
            categories[category].ues.add(h.ue);

            if (h.method === 'ML') {
                categories[category].ml++;
            } else {
                categories[category].a3++;
            }

            if (h.rsrp) categories[category].rsrpSum += h.rsrp;
            if (h.sinr) categories[category].sinrSum += h.sinr;
        });

        // Calculate averages and reduction
        for (const category of Object.keys(categories)) {
            const cat = categories[category];
            if (cat.total > 0) {
                cat.avgRSRP = (cat.rsrpSum / cat.total).toFixed(1);
                cat.avgSINR = (cat.sinrSum / cat.total).toFixed(1);
            }
            cat.ueCount = cat.ues.size;
            cat.reduction = cat.a3 > 0 && cat.ml > 0
                ? ((cat.a3 - cat.ml) / cat.a3 * 100).toFixed(0)
                : null;
        }

        // Detect ping-pongs per category
        const sortedHistory = [...history].sort((a, b) => a.timestamp - b.timestamp);
        const lastHandovers = {};

        sortedHistory.forEach(h => {
            const key = h.ue;
            const prev = lastHandovers[key];

            if (prev && prev.to === h.from && prev.from === h.to) {
                const timeDiff = (h.timestamp - prev.timestamp) / 1000;
                if (timeDiff < 10) {
                    const category = categorizeUE(h.ue);
                    if (categories[category]) {
                        categories[category].pingPongs++;
                    }
                }
            }
            lastHandovers[key] = h;
        });

        // Convert to sorted array
        const sorted = Object.values(categories)
            .filter(c => c.total > 0)
            .sort((a, b) => b.total - a.total);

        return {
            categories: sorted,
            hasData: sorted.length > 0,
            totalHandovers: history.length
        };
    }, [history]);

    if (!analysis.hasData) {
        return (
            <div className="card">
                <div className="card-header">📊 Handover Analysis by UE Type</div>
                <div className="card-body text-center text-gray-500 py-8">
                    No handover data available
                </div>
            </div>
        );
    }

    return (
        <div className="card">
            <div className="card-header">📊 Handover Analysis by UE Type</div>
            <div className="card-body">
                {/* Summary bar chart */}
                <div className="mb-4">
                    <div className="text-sm text-gray-600 mb-2">Distribution by Category</div>
                    <div className="flex gap-1 h-8 rounded overflow-hidden">
                        {analysis.categories.map(cat => (
                            <div
                                key={cat.name}
                                className={`flex items-center justify-center text-xs font-medium ${cat.color}`}
                                style={{ width: `${(cat.total / analysis.totalHandovers) * 100}%` }}
                                title={`${cat.name}: ${cat.total} (${((cat.total / analysis.totalHandovers) * 100).toFixed(1)}%)`}
                            >
                                {cat.total > analysis.totalHandovers * 0.08 && (
                                    <span>{cat.icon} {cat.total}</span>
                                )}
                            </div>
                        ))}
                    </div>
                </div>

                {/* Detailed table */}
                <table className="w-full text-sm">
                    <thead className="bg-gray-50">
                        <tr>
                            <th className="text-left px-3 py-2">Category</th>
                            <th className="text-center px-3 py-2">UEs</th>
                            <th className="text-center px-3 py-2">
                                <span className="text-green-600">ML</span>
                            </th>
                            <th className="text-center px-3 py-2">
                                <span className="text-orange-600">A3</span>
                            </th>
                            <th className="text-center px-3 py-2">Reduction</th>
                            <th className="text-center px-3 py-2">Avg RSRP</th>
                            <th className="text-center px-3 py-2">Ping-Pongs</th>
                        </tr>
                    </thead>
                    <tbody>
                        {analysis.categories.map(cat => (
                            <tr key={cat.name} className="border-t hover:bg-gray-50">
                                <td className="px-3 py-2">
                                    <div className="flex items-center gap-2">
                                        <span className="text-lg">{cat.icon}</span>
                                        <div>
                                            <div className="font-medium">{cat.name}</div>
                                            <div className="text-xs text-gray-500">{cat.description}</div>
                                        </div>
                                    </div>
                                </td>
                                <td className="text-center px-3 py-2 text-gray-600">
                                    {cat.ueCount}
                                </td>
                                <td className="text-center px-3 py-2">
                                    <span className="font-semibold text-green-600">{cat.ml}</span>
                                </td>
                                <td className="text-center px-3 py-2">
                                    <span className="font-semibold text-orange-600">{cat.a3}</span>
                                </td>
                                <td className="text-center px-3 py-2">
                                    {cat.reduction !== null ? (
                                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${parseInt(cat.reduction) > 50
                                                ? 'bg-green-100 text-green-800'
                                                : parseInt(cat.reduction) > 0
                                                    ? 'bg-yellow-100 text-yellow-800'
                                                    : 'bg-gray-100 text-gray-600'
                                            }`}>
                                            {parseInt(cat.reduction) > 0 ? `${cat.reduction}% ↓` : 'N/A'}
                                        </span>
                                    ) : (
                                        <span className="text-gray-400">-</span>
                                    )}
                                </td>
                                <td className="text-center px-3 py-2 font-mono text-xs">
                                    {cat.avgRSRP} dBm
                                </td>
                                <td className="text-center px-3 py-2">
                                    {cat.pingPongs > 0 ? (
                                        <span className="px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-800">
                                            {cat.pingPongs}
                                        </span>
                                    ) : (
                                        <span className="text-green-600">0</span>
                                    )}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>

                {/* Key insights */}
                <div className="mt-4 text-xs text-gray-600 border-t pt-3">
                    <strong>Key Insight:</strong>{' '}
                    {analysis.categories.length > 0 && (
                        <>
                            {(() => {
                                const bestReduction = analysis.categories
                                    .filter(c => c.reduction !== null && c.ml > 0 && c.a3 > 0)
                                    .sort((a, b) => parseInt(b.reduction) - parseInt(a.reduction))[0];

                                const mostPingPongs = analysis.categories
                                    .filter(c => c.pingPongs > 0)
                                    .sort((a, b) => b.pingPongs - a.pingPongs)[0];

                                return (
                                    <>
                                        {bestReduction && (
                                            <span>
                                                {bestReduction.icon} <strong>{bestReduction.name}</strong> shows
                                                highest ML benefit ({bestReduction.reduction}% reduction).
                                            </span>
                                        )}
                                        {mostPingPongs && (
                                            <span className="ml-2">
                                                {mostPingPongs.icon} <strong>{mostPingPongs.name}</strong> has
                                                most ping-pongs ({mostPingPongs.pingPongs}) - consider tuning.
                                            </span>
                                        )}
                                    </>
                                );
                            })()}
                        </>
                    )}
                </div>
            </div>
        </div>
    );
}
