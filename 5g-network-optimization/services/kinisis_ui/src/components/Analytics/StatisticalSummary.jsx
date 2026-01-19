import { useMemo } from 'react';
import {
    welchTTest,
    confidenceInterval,
    cohensD,
    coefficientOfVariation,
    getCountsPerRetry
} from '../../utils/statistics';

export default function StatisticalSummary({ history }) {
    const stats = useMemo(() => {
        // Separate by method
        const a3Handovers = history.filter(h => h.method !== 'ML');
        const mlHandovers = history.filter(h => h.method === 'ML');

        // Get counts per retry for each mode
        const a3Counts = getCountsPerRetry(a3Handovers);
        const mlCounts = getCountsPerRetry(mlHandovers);

        // Statistical tests
        const tTest = welchTTest(a3Counts, mlCounts);
        const a3CI = confidenceInterval(a3Counts);
        const mlCI = confidenceInterval(mlCounts);
        const effectSize = cohensD(a3Counts, mlCounts);
        const a3Stability = coefficientOfVariation(a3Counts);
        const mlStability = coefficientOfVariation(mlCounts);

        // Improvement calculation
        const improvement = mlCI.mean > 0
            ? ((a3CI.mean - mlCI.mean) / a3CI.mean * 100)
            : 0;
        const improvementRatio = mlCI.mean > 0 ? a3CI.mean / mlCI.mean : 0;

        // Minimum runs check (need at least 3 for meaningful statistics)
        const minRuns = 3;
        const hasEnoughData = a3Counts.length >= minRuns && mlCounts.length >= minRuns;

        return {
            tTest,
            a3: {
                ci: a3CI,
                stability: a3Stability,
                n: a3Counts.length,
                total: a3Handovers.length
            },
            ml: {
                ci: mlCI,
                stability: mlStability,
                n: mlCounts.length,
                total: mlHandovers.length
            },
            effectSize,
            improvement,
            improvementRatio,
            hasEnoughData,
            minRunsNeeded: Math.max(minRuns - a3Counts.length, minRuns - mlCounts.length, 0)
        };
    }, [history]);

    const getSignificanceStars = (pValue) => {
        if (pValue < 0.001) return { stars: '★★★', label: 'p < 0.001', color: 'text-green-600' };
        if (pValue < 0.01) return { stars: '★★', label: 'p < 0.01', color: 'text-green-600' };
        if (pValue < 0.05) return { stars: '★', label: 'p < 0.05', color: 'text-green-600' };
        return { stars: 'ns', label: `p = ${pValue.toFixed(3)}`, color: 'text-gray-500' };
    };

    const getEffectSizeLabel = (d) => {
        const absD = Math.abs(d);
        if (absD >= 0.8) return { label: 'Large', color: 'bg-green-100 text-green-800', icon: '🟢' };
        if (absD >= 0.5) return { label: 'Medium', color: 'bg-yellow-100 text-yellow-800', icon: '🟡' };
        if (absD >= 0.2) return { label: 'Small', color: 'bg-orange-100 text-orange-800', icon: '🟠' };
        return { label: 'Negligible', color: 'bg-red-100 text-red-800', icon: '🔴' };
    };

    const significance = getSignificanceStars(stats.tTest.pValue);
    const effectLabel = getEffectSizeLabel(stats.effectSize.d);

    return (
        <div className="card">
            <div className="card-header">📊 Statistical Summary</div>
            <div className="card-body">
                {/* Data insufficiency warning */}
                {!stats.hasEnoughData && (
                    <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 mb-4">
                        <div className="flex items-center gap-2 text-yellow-800">
                            <span>⚠️</span>
                            <span className="font-medium">
                                Need {stats.minRunsNeeded} more runs for reliable statistics
                            </span>
                        </div>
                        <div className="text-sm text-yellow-700 mt-1">
                            Currently: A3 = {stats.a3.n} runs, ML = {stats.ml.n} runs (need 3+ each)
                        </div>
                    </div>
                )}

                {/* Main statistics table */}
                <table className="w-full text-sm">
                    <thead className="bg-gray-50">
                        <tr>
                            <th className="text-left px-4 py-2">Metric</th>
                            <th className="text-left px-4 py-2">A3 (Baseline)</th>
                            <th className="text-left px-4 py-2">ML (Proposed)</th>
                            <th className="text-left px-4 py-2">Result</th>
                        </tr>
                    </thead>
                    <tbody>
                        {/* Handover Count with Confidence Interval */}
                        <tr className="border-t">
                            <td className="px-4 py-2 font-medium">
                                Handover Count
                                <div className="text-xs text-gray-500">per run (95% CI)</div>
                            </td>
                            <td className="px-4 py-2">
                                <div className="font-semibold">{stats.a3.ci.mean.toFixed(1)}</div>
                                <div className="text-xs text-gray-500">
                                    ± {stats.a3.ci.margin.toFixed(1)} ({stats.a3.ci.lower.toFixed(1)} - {stats.a3.ci.upper.toFixed(1)})
                                </div>
                            </td>
                            <td className="px-4 py-2">
                                <div className="font-semibold">{stats.ml.ci.mean.toFixed(1)}</div>
                                <div className="text-xs text-gray-500">
                                    ± {stats.ml.ci.margin.toFixed(1)} ({stats.ml.ci.lower.toFixed(1)} - {stats.ml.ci.upper.toFixed(1)})
                                </div>
                            </td>
                            <td className="px-4 py-2">
                                <span className="text-green-600 font-bold">
                                    {stats.improvement > 0 ? `${stats.improvement.toFixed(1)}% ↓` : '-'}
                                </span>
                            </td>
                        </tr>

                        {/* Sample Size */}
                        <tr className="border-t bg-gray-50">
                            <td className="px-4 py-2 font-medium">Sample Size (n)</td>
                            <td className="px-4 py-2">{stats.a3.n} runs</td>
                            <td className="px-4 py-2">{stats.ml.n} runs</td>
                            <td className="px-4 py-2 text-gray-500">
                                {stats.a3.total + stats.ml.total} total HOs
                            </td>
                        </tr>

                        {/* P-Value (NEW) */}
                        <tr className="border-t">
                            <td className="px-4 py-2 font-medium">
                                P-Value
                                <div className="text-xs text-gray-500">Welch's t-test</div>
                            </td>
                            <td colSpan="2" className="px-4 py-2 text-center">
                                <span className="font-mono">
                                    t({stats.tTest.df.toFixed(1)}) = {stats.tTest.t.toFixed(3)}
                                </span>
                            </td>
                            <td className={`px-4 py-2 font-medium ${significance.color}`}>
                                <span className="mr-1">{significance.stars}</span>
                                <span className="text-xs">{significance.label}</span>
                            </td>
                        </tr>

                        {/* Effect Size */}
                        <tr className="border-t bg-gray-50">
                            <td className="px-4 py-2 font-medium">Effect Size (Cohen's d)</td>
                            <td colSpan="2" className="px-4 py-2 text-center font-mono">
                                {stats.effectSize.d.toFixed(3)}
                            </td>
                            <td className="px-4 py-2">
                                <span className={`px-2 py-1 rounded text-xs font-medium ${effectLabel.color}`}>
                                    {effectLabel.icon} {effectLabel.label}
                                </span>
                            </td>
                        </tr>

                        {/* Stability (CV) */}
                        <tr className="border-t">
                            <td className="px-4 py-2 font-medium">
                                Stability (CV)
                                <div className="text-xs text-gray-500">lower = more consistent</div>
                            </td>
                            <td className="px-4 py-2">
                                {stats.a3.stability.cv.toFixed(1)}%
                                <span className="text-xs text-gray-500 ml-1">
                                    ({stats.a3.stability.interpretation})
                                </span>
                            </td>
                            <td className="px-4 py-2">
                                {stats.ml.stability.cv.toFixed(1)}%
                                <span className="text-xs text-gray-500 ml-1">
                                    ({stats.ml.stability.interpretation})
                                </span>
                            </td>
                            <td className="px-4 py-2 text-gray-500">-</td>
                        </tr>
                    </tbody>
                </table>

                {/* Significance interpretation */}
                {stats.hasEnoughData && stats.tTest.significant && stats.improvement > 20 && (
                    <div className="mt-4 p-3 bg-green-50 border border-green-200 rounded-lg">
                        <div className="text-green-800 font-medium flex items-center gap-2">
                            ✅ Statistically significant improvement detected!
                        </div>
                        <div className="text-sm text-green-700 mt-1">
                            ML reduces handovers by <strong>{stats.improvement.toFixed(0)}%</strong> compared to A3
                            (p {stats.tTest.pValue < 0.001 ? '< 0.001' : `= ${stats.tTest.pValue.toFixed(3)}`},
                            d = {stats.effectSize.d.toFixed(2)}).
                        </div>
                    </div>
                )}

                {/* Non-significant result */}
                {stats.hasEnoughData && !stats.tTest.significant && (
                    <div className="mt-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
                        <div className="text-yellow-800 font-medium flex items-center gap-2">
                            ⚠️ Results not statistically significant (p = {stats.tTest.pValue.toFixed(3)})
                        </div>
                        <div className="text-sm text-yellow-700 mt-1">
                            More runs may be needed to establish significance. Current effect size: {stats.effectSize.interpretation}.
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}

