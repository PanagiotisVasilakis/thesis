import { useMemo } from 'react';
import {
    coefficientOfVariation,
    linearRegression,
    mean,
    stdDev,
    getCountsPerRetry
} from '../../utils/statistics';

/**
 * Stability Analysis Component
 * Analyzes consistency of handover counts across experiment runs to validate reproducibility
 */

export default function StabilityAnalysis({ history }) {
    const analysis = useMemo(() => {
        // Separate by method
        const mlHandovers = history.filter(h => h.method === 'ML');
        const a3Handovers = history.filter(h => h.method !== 'ML');

        // Get counts per retry
        const mlCounts = getCountsPerRetry(mlHandovers);
        const a3Counts = getCountsPerRetry(a3Handovers);

        // Skip if not enough data
        if (mlCounts.length < 2 && a3Counts.length < 2) {
            return { hasData: false };
        }

        // Calculate stability metrics
        const mlCV = coefficientOfVariation(mlCounts);
        const a3CV = coefficientOfVariation(a3Counts);

        // Trend analysis
        const mlTrend = linearRegression(mlCounts);
        const a3Trend = linearRegression(a3Counts);

        // Min/max range
        const mlMin = mlCounts.length > 0 ? Math.min(...mlCounts) : 0;
        const mlMax = mlCounts.length > 0 ? Math.max(...mlCounts) : 0;
        const a3Min = a3Counts.length > 0 ? Math.min(...a3Counts) : 0;
        const a3Max = a3Counts.length > 0 ? Math.max(...a3Counts) : 0;

        // Calculate mean and std dev
        const mlMean = mean(mlCounts);
        const mlStd = stdDev(mlCounts);
        const a3Mean = mean(a3Counts);
        const a3Std = stdDev(a3Counts);

        return {
            hasData: true,
            ml: {
                counts: mlCounts,
                cv: mlCV,
                trend: mlTrend,
                min: mlMin,
                max: mlMax,
                mean: mlMean,
                std: mlStd,
                n: mlCounts.length
            },
            a3: {
                counts: a3Counts,
                cv: a3CV,
                trend: a3Trend,
                min: a3Min,
                max: a3Max,
                mean: a3Mean,
                std: a3Std,
                n: a3Counts.length
            }
        };
    }, [history]);

    if (!analysis.hasData) {
        return (
            <div className="card">
                <div className="card-header">📈 Experiment Stability Analysis</div>
                <div className="card-body text-center text-gray-500 py-8">
                    Need at least 2 experiment runs to analyze stability
                </div>
            </div>
        );
    }

    // Helper for stability badge
    const getStabilityBadge = (cv) => {
        if (cv.cv < 10) return { label: 'Excellent', color: 'bg-green-100 text-green-800' };
        if (cv.cv < 15) return { label: 'Good', color: 'bg-blue-100 text-blue-800' };
        if (cv.cv < 25) return { label: 'Fair', color: 'bg-yellow-100 text-yellow-800' };
        return { label: 'Poor', color: 'bg-red-100 text-red-800' };
    };

    // Helper for trend indicator
    const getTrendIndicator = (trend) => {
        if (!trend.hasTrend) return { icon: '→', label: 'Stable', color: 'text-green-600' };
        if (trend.trendDirection === 'increasing') return { icon: '↗', label: 'Increasing', color: 'text-orange-600' };
        return { icon: '↘', label: 'Decreasing', color: 'text-blue-600' };
    };

    // Scale for mini chart
    const maxCount = Math.max(
        ...analysis.ml.counts,
        ...analysis.a3.counts,
        1
    );

    return (
        <div className="card">
            <div className="card-header">📈 Experiment Stability Analysis</div>
            <div className="card-body">
                {/* Retry-by-retry visualization */}
                <div className="mb-4">
                    <div className="text-sm text-gray-600 mb-2">Handover Counts Per Retry</div>
                    <div className="grid grid-cols-2 gap-4">
                        {/* ML Chart */}
                        <div className="bg-gray-50 rounded-lg p-3">
                            <div className="text-xs font-medium text-green-600 mb-2">
                                ML Mode ({analysis.ml.n} runs)
                            </div>
                            <div className="flex items-end gap-1 h-16">
                                {analysis.ml.counts.map((count, i) => (
                                    <div
                                        key={i}
                                        className="flex-1 bg-green-500 rounded-t hover:bg-green-600 transition-colors"
                                        style={{ height: `${(count / maxCount) * 100}%` }}
                                        title={`Run ${i + 1}: ${count} handovers`}
                                    />
                                ))}
                            </div>
                            <div className="flex justify-between text-xs text-gray-500 mt-1">
                                <span>Run 1</span>
                                <span>Run {analysis.ml.n}</span>
                            </div>
                        </div>

                        {/* A3 Chart */}
                        <div className="bg-gray-50 rounded-lg p-3">
                            <div className="text-xs font-medium text-orange-600 mb-2">
                                A3 Mode ({analysis.a3.n} runs)
                            </div>
                            <div className="flex items-end gap-1 h-16">
                                {analysis.a3.counts.map((count, i) => (
                                    <div
                                        key={i}
                                        className="flex-1 bg-orange-500 rounded-t hover:bg-orange-600 transition-colors"
                                        style={{ height: `${(count / maxCount) * 100}%` }}
                                        title={`Run ${i + 1}: ${count} handovers`}
                                    />
                                ))}
                            </div>
                            <div className="flex justify-between text-xs text-gray-500 mt-1">
                                <span>Run 1</span>
                                <span>Run {analysis.a3.n}</span>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Stability metrics table */}
                <table className="w-full text-sm">
                    <thead className="bg-gray-50">
                        <tr>
                            <th className="text-left px-3 py-2">Metric</th>
                            <th className="text-center px-3 py-2 text-green-600">ML Mode</th>
                            <th className="text-center px-3 py-2 text-orange-600">A3 Mode</th>
                        </tr>
                    </thead>
                    <tbody>
                        {/* Coefficient of Variation */}
                        <tr className="border-t">
                            <td className="px-3 py-2">
                                <div className="font-medium">Coefficient of Variation</div>
                                <div className="text-xs text-gray-500">Lower = more consistent</div>
                            </td>
                            <td className="text-center px-3 py-2">
                                <div className="font-mono">{analysis.ml.cv.cv.toFixed(1)}%</div>
                                <span className={`text-xs px-2 py-0.5 rounded ${getStabilityBadge(analysis.ml.cv).color}`}>
                                    {getStabilityBadge(analysis.ml.cv).label}
                                </span>
                            </td>
                            <td className="text-center px-3 py-2">
                                <div className="font-mono">{analysis.a3.cv.cv.toFixed(1)}%</div>
                                <span className={`text-xs px-2 py-0.5 rounded ${getStabilityBadge(analysis.a3.cv).color}`}>
                                    {getStabilityBadge(analysis.a3.cv).label}
                                </span>
                            </td>
                        </tr>

                        {/* Range */}
                        <tr className="border-t bg-gray-50">
                            <td className="px-3 py-2">
                                <div className="font-medium">Range (Min - Max)</div>
                                <div className="text-xs text-gray-500">Narrower = more stable</div>
                            </td>
                            <td className="text-center px-3 py-2 font-mono text-sm">
                                {analysis.ml.min} - {analysis.ml.max}
                                <span className="text-xs text-gray-500 ml-1">
                                    (Δ{analysis.ml.max - analysis.ml.min})
                                </span>
                            </td>
                            <td className="text-center px-3 py-2 font-mono text-sm">
                                {analysis.a3.min} - {analysis.a3.max}
                                <span className="text-xs text-gray-500 ml-1">
                                    (Δ{analysis.a3.max - analysis.a3.min})
                                </span>
                            </td>
                        </tr>

                        {/* Mean ± Std */}
                        <tr className="border-t">
                            <td className="px-3 py-2">
                                <div className="font-medium">Mean ± Std Dev</div>
                            </td>
                            <td className="text-center px-3 py-2 font-mono text-sm">
                                {analysis.ml.mean.toFixed(1)} ± {analysis.ml.std.toFixed(1)}
                            </td>
                            <td className="text-center px-3 py-2 font-mono text-sm">
                                {analysis.a3.mean.toFixed(1)} ± {analysis.a3.std.toFixed(1)}
                            </td>
                        </tr>

                        {/* Trend */}
                        <tr className="border-t bg-gray-50">
                            <td className="px-3 py-2">
                                <div className="font-medium">Trend Over Runs</div>
                                <div className="text-xs text-gray-500">Stable = reproducible</div>
                            </td>
                            <td className="text-center px-3 py-2">
                                <span className={`font-medium ${getTrendIndicator(analysis.ml.trend).color}`}>
                                    {getTrendIndicator(analysis.ml.trend).icon} {getTrendIndicator(analysis.ml.trend).label}
                                </span>
                                <div className="text-xs text-gray-500">
                                    slope: {analysis.ml.trend.slope.toFixed(2)}/run
                                </div>
                            </td>
                            <td className="text-center px-3 py-2">
                                <span className={`font-medium ${getTrendIndicator(analysis.a3.trend).color}`}>
                                    {getTrendIndicator(analysis.a3.trend).icon} {getTrendIndicator(analysis.a3.trend).label}
                                </span>
                                <div className="text-xs text-gray-500">
                                    slope: {analysis.a3.trend.slope.toFixed(2)}/run
                                </div>
                            </td>
                        </tr>

                        {/* R-squared for trend fit */}
                        <tr className="border-t">
                            <td className="px-3 py-2">
                                <div className="font-medium">Trend R²</div>
                                <div className="text-xs text-gray-500">Higher = stronger trend</div>
                            </td>
                            <td className="text-center px-3 py-2 font-mono text-sm">
                                {analysis.ml.trend.rSquared.toFixed(3)}
                            </td>
                            <td className="text-center px-3 py-2 font-mono text-sm">
                                {analysis.a3.trend.rSquared.toFixed(3)}
                            </td>
                        </tr>
                    </tbody>
                </table>

                {/* Interpretation */}
                <div className="mt-4 text-xs border-t pt-3">
                    {analysis.ml.cv.cv < 15 && analysis.a3.cv.cv < 15 ? (
                        <div className="text-green-700 bg-green-50 p-2 rounded">
                            ✅ <strong>Excellent reproducibility:</strong> Both ML and A3 experiments show
                            consistent results across runs (CV &lt; 15%). Your data is reliable for thesis conclusions.
                        </div>
                    ) : (
                        <div className="text-yellow-700 bg-yellow-50 p-2 rounded">
                            ⚠️ <strong>Moderate variability detected:</strong> Consider running more experiments
                            to improve statistical confidence. {analysis.ml.cv.cv > 25 && 'ML mode shows high variance. '}
                            {analysis.a3.cv.cv > 25 && 'A3 mode shows high variance.'}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
