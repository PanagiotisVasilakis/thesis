import { useMemo } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';

export default function ConfidenceDistribution({ history }) {
    const analysis = useMemo(() => {
        if (!history || history.length === 0) {
            return { bins: [], summary: null };
        }

        // Filter ML events only (they have confidence)
        const mlEvents = history.filter(h => h.method === 'ML' && h.confidence);

        if (mlEvents.length === 0) {
            return { bins: [], summary: null };
        }

        // Define confidence bins
        const bins = [
            { range: '0.50-0.60', min: 0.5, max: 0.6, count: 0, color: '#ef4444' },
            { range: '0.60-0.70', min: 0.6, max: 0.7, count: 0, color: '#f97316' },
            { range: '0.70-0.80', min: 0.7, max: 0.8, count: 0, color: '#eab308' },
            { range: '0.80-0.90', min: 0.8, max: 0.9, count: 0, color: '#84cc16' },
            { range: '0.90-0.95', min: 0.9, max: 0.95, count: 0, color: '#22c55e' },
            { range: '0.95-1.00', min: 0.95, max: 1.0, count: 0, color: '#10b981' },
        ];

        // Count events in each bin
        mlEvents.forEach(event => {
            const conf = parseFloat(event.confidence);
            for (const bin of bins) {
                if (conf >= bin.min && conf < bin.max) {
                    bin.count++;
                    break;
                }
                // Handle edge case for 1.0
                if (conf >= 0.95 && bin.range === '0.95-1.00') {
                    bin.count++;
                    break;
                }
            }
        });

        // Calculate percentages
        const total = mlEvents.length;
        bins.forEach(bin => {
            bin.percentage = ((bin.count / total) * 100).toFixed(1);
        });

        // Calculate summary stats
        const confidences = mlEvents.map(e => parseFloat(e.confidence));
        const mean = confidences.reduce((a, b) => a + b, 0) / confidences.length;
        const sorted = [...confidences].sort((a, b) => a - b);
        const median = sorted[Math.floor(sorted.length / 2)];
        const min = Math.min(...confidences);
        const max = Math.max(...confidences);

        // Count high confidence decisions
        const highConf = confidences.filter(c => c >= 0.9).length;
        const veryHighConf = confidences.filter(c => c >= 0.95).length;

        return {
            bins,
            summary: {
                total,
                mean: mean.toFixed(3),
                median: median.toFixed(3),
                min: min.toFixed(3),
                max: max.toFixed(3),
                highConfPct: ((highConf / total) * 100).toFixed(1),
                veryHighConfPct: ((veryHighConf / total) * 100).toFixed(1),
            }
        };
    }, [history]);

    if (!analysis.summary) {
        return (
            <div className="card">
                <div className="card-header">🎯 Confidence Distribution</div>
                <div className="card-body text-center text-gray-500 py-8">
                    Run ML experiments to see confidence distribution
                </div>
            </div>
        );
    }

    return (
        <div className="card">
            <div className="card-header">🎯 Confidence Distribution</div>
            <div className="card-body">
                {/* Summary Stats */}
                <div className="grid grid-cols-4 gap-2 mb-4 text-center">
                    <div className="bg-gray-50 rounded p-2">
                        <div className="text-lg font-bold">{analysis.summary.total}</div>
                        <div className="text-xs text-gray-500">ML Decisions</div>
                    </div>
                    <div className="bg-gray-50 rounded p-2">
                        <div className="text-lg font-bold">{analysis.summary.mean}</div>
                        <div className="text-xs text-gray-500">Mean Conf.</div>
                    </div>
                    <div className="bg-green-50 rounded p-2">
                        <div className="text-lg font-bold text-green-600">{analysis.summary.highConfPct}%</div>
                        <div className="text-xs text-gray-500">≥90% Conf.</div>
                    </div>
                    <div className="bg-emerald-50 rounded p-2">
                        <div className="text-lg font-bold text-emerald-600">{analysis.summary.veryHighConfPct}%</div>
                        <div className="text-xs text-gray-500">≥95% Conf.</div>
                    </div>
                </div>

                {/* Histogram */}
                <div className="h-48">
                    <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={analysis.bins}>
                            <CartesianGrid strokeDasharray="3 3" />
                            <XAxis dataKey="range" tick={{ fontSize: 10 }} />
                            <YAxis label={{ value: 'Count', angle: -90, position: 'insideLeft', fontSize: 12 }} />
                            <Tooltip
                                formatter={(value, name, props) => [
                                    `${value} (${props.payload.percentage}%)`,
                                    'Events'
                                ]}
                            />
                            <Bar dataKey="count" name="Events">
                                {analysis.bins.map((entry, index) => (
                                    <Cell key={`cell-${index}`} fill={entry.color} />
                                ))}
                            </Bar>
                        </BarChart>
                    </ResponsiveContainer>
                </div>

                {/* Interpretation */}
                <div className="mt-4 text-sm text-gray-600">
                    <div className="font-medium mb-1">Interpretation:</div>
                    {parseFloat(analysis.summary.highConfPct) >= 70 ? (
                        <div className="text-green-600">
                            ✅ Excellent: {analysis.summary.highConfPct}% of ML decisions have ≥90% confidence
                        </div>
                    ) : parseFloat(analysis.summary.highConfPct) >= 50 ? (
                        <div className="text-yellow-600">
                            ⚠️ Good: {analysis.summary.highConfPct}% of decisions are high-confidence
                        </div>
                    ) : (
                        <div className="text-red-600">
                            ⚠️ Low confidence: Consider retraining model or adjusting thresholds
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
