/**
 * Statistical Analysis Utilities for Handover Analytics
 * 
 * Provides professional-grade statistical functions for:
 * - Welch's t-test (unequal variances)
 * - Confidence intervals
 * - Effect size (Cohen's d)
 * - Coefficient of variation
 * - Linear regression for trend analysis
 */

// ============================================
// Core Statistical Functions
// ============================================

/**
 * Calculate mean of an array
 */
export function mean(data) {
    if (!data || data.length === 0) return 0;
    return data.reduce((sum, x) => sum + x, 0) / data.length;
}

/**
 * Calculate sample standard deviation
 */
export function stdDev(data) {
    if (!data || data.length < 2) return 0;
    const avg = mean(data);
    const squaredDiffs = data.map(x => (x - avg) ** 2);
    return Math.sqrt(squaredDiffs.reduce((sum, x) => sum + x, 0) / (data.length - 1));
}

/**
 * Calculate sample variance
 */
export function variance(data) {
    if (!data || data.length < 2) return 0;
    const avg = mean(data);
    return data.reduce((sum, x) => sum + (x - avg) ** 2, 0) / (data.length - 1);
}

/**
 * Calculate standard error of the mean
 */
export function standardError(data) {
    if (!data || data.length < 2) return 0;
    return stdDev(data) / Math.sqrt(data.length);
}

// ============================================
// T-Distribution Functions
// ============================================

/**
 * Approximation of the t-distribution CDF using the beta function
 * Based on Algorithm AS 3 from Applied Statistics
 */
function betaIncomplete(a, b, x) {
    if (x === 0 || x === 1) return x;

    // Use continued fraction approximation
    const maxIterations = 200;
    const epsilon = 1e-10;

    let bt = Math.exp(
        lgamma(a + b) - lgamma(a) - lgamma(b) +
        a * Math.log(x) + b * Math.log(1 - x)
    );

    if (x < (a + 1) / (a + b + 2)) {
        return bt * betaCF(a, b, x) / a;
    } else {
        return 1 - bt * betaCF(b, a, 1 - x) / b;
    }
}

/**
 * Continued fraction for incomplete beta function
 */
function betaCF(a, b, x) {
    const maxIterations = 200;
    const epsilon = 1e-10;

    let qab = a + b;
    let qap = a + 1;
    let qam = a - 1;
    let c = 1;
    let d = 1 - qab * x / qap;

    if (Math.abs(d) < epsilon) d = epsilon;
    d = 1 / d;
    let h = d;

    for (let m = 1; m <= maxIterations; m++) {
        let m2 = 2 * m;
        let aa = m * (b - m) * x / ((qam + m2) * (a + m2));
        d = 1 + aa * d;
        if (Math.abs(d) < epsilon) d = epsilon;
        c = 1 + aa / c;
        if (Math.abs(c) < epsilon) c = epsilon;
        d = 1 / d;
        h *= d * c;

        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2));
        d = 1 + aa * d;
        if (Math.abs(d) < epsilon) d = epsilon;
        c = 1 + aa / c;
        if (Math.abs(c) < epsilon) c = epsilon;
        d = 1 / d;
        let del = d * c;
        h *= del;

        if (Math.abs(del - 1) < epsilon) break;
    }

    return h;
}

/**
 * Log gamma function approximation (Lanczos)
 */
function lgamma(x) {
    const g = 7;
    const c = [
        0.99999999999980993,
        676.5203681218851,
        -1259.1392167224028,
        771.32342877765313,
        -176.61502916214059,
        12.507343278686905,
        -0.13857109526572012,
        9.9843695780195716e-6,
        1.5056327351493116e-7
    ];

    if (x < 0.5) {
        return Math.log(Math.PI / Math.sin(Math.PI * x)) - lgamma(1 - x);
    }

    x -= 1;
    let a = c[0];
    const t = x + g + 0.5;

    for (let i = 1; i < g + 2; i++) {
        a += c[i] / (x + i);
    }

    return 0.5 * Math.log(2 * Math.PI) + (x + 0.5) * Math.log(t) - t + Math.log(a);
}

/**
 * T-distribution CDF
 */
function tDistCDF(t, df) {
    const x = df / (df + t * t);
    return 1 - 0.5 * betaIncomplete(df / 2, 0.5, x);
}

/**
 * Calculate two-tailed p-value from t-statistic
 */
export function tDistributionPValue(t, df) {
    if (df <= 0) return 1;
    const cdf = tDistCDF(Math.abs(t), df);
    return 2 * (1 - cdf);
}

/**
 * Get t-critical value for given confidence level
 * Uses approximation for common values
 */
export function getTCritical(df, confidenceLevel = 0.95) {
    const alpha = 1 - confidenceLevel;

    // Common t-critical values (two-tailed)
    // For more precision, we use approximation
    if (df <= 0) return 1.96;

    // Approximation for large df
    if (df > 100) return 1.96;

    // Lookup table for common df values at 95% CI
    const tTable95 = {
        1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
        6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
        11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
        16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
        25: 2.060, 30: 2.042, 40: 2.021, 50: 2.009, 60: 2.000,
        80: 1.990, 100: 1.984
    };

    // Find closest value
    const keys = Object.keys(tTable95).map(Number).sort((a, b) => a - b);
    for (let i = 0; i < keys.length; i++) {
        if (df <= keys[i]) {
            return tTable95[keys[i]];
        }
    }
    return 1.96;
}

// ============================================
// Welch's T-Test
// ============================================

/**
 * Calculate Welch-Satterthwaite degrees of freedom
 */
function welchDF(var1, var2, n1, n2) {
    const se1 = var1 / n1;
    const se2 = var2 / n2;
    const numerator = (se1 + se2) ** 2;
    const denominator = (se1 ** 2) / (n1 - 1) + (se2 ** 2) / (n2 - 1);
    return numerator / denominator;
}

/**
 * Perform Welch's t-test (unequal variances)
 * 
 * @param {number[]} sample1 - First sample array
 * @param {number[]} sample2 - Second sample array
 * @returns {Object} Test results including t-statistic, df, p-value
 */
export function welchTTest(sample1, sample2) {
    if (!sample1 || !sample2 || sample1.length < 2 || sample2.length < 2) {
        return {
            t: 0,
            df: 0,
            pValue: 1,
            mean1: mean(sample1 || []),
            mean2: mean(sample2 || []),
            significant: false,
            significanceLevel: 'ns'
        };
    }

    const n1 = sample1.length;
    const n2 = sample2.length;
    const mean1 = mean(sample1);
    const mean2 = mean(sample2);
    const var1 = variance(sample1);
    const var2 = variance(sample2);

    // Standard error of the difference
    const se = Math.sqrt(var1 / n1 + var2 / n2);

    // Welch's t-statistic
    const t = (mean1 - mean2) / se;

    // Welch-Satterthwaite degrees of freedom
    const df = welchDF(var1, var2, n1, n2);

    // Two-tailed p-value
    const pValue = tDistributionPValue(t, df);

    // Determine significance level
    let significanceLevel = 'ns';
    if (pValue < 0.001) significanceLevel = '***';
    else if (pValue < 0.01) significanceLevel = '**';
    else if (pValue < 0.05) significanceLevel = '*';

    return {
        t: Number(t.toFixed(4)),
        df: Number(df.toFixed(2)),
        pValue: Number(pValue.toFixed(6)),
        mean1: Number(mean1.toFixed(2)),
        mean2: Number(mean2.toFixed(2)),
        sampleSize1: n1,
        sampleSize2: n2,
        significant: pValue < 0.05,
        significanceLevel
    };
}

// ============================================
// Confidence Intervals
// ============================================

/**
 * Calculate confidence interval for a sample
 * 
 * @param {number[]} data - Sample data
 * @param {number} confidenceLevel - Confidence level (default 0.95)
 * @returns {Object} CI with mean, lower, upper bounds
 */
export function confidenceInterval(data, confidenceLevel = 0.95) {
    if (!data || data.length < 2) {
        return {
            mean: mean(data || []),
            lower: 0,
            upper: 0,
            margin: 0,
            stderr: 0,
            n: data?.length || 0
        };
    }

    const n = data.length;
    const avg = mean(data);
    const se = standardError(data);
    const df = n - 1;
    const tCritical = getTCritical(df, confidenceLevel);
    const margin = tCritical * se;

    return {
        mean: Number(avg.toFixed(2)),
        lower: Number((avg - margin).toFixed(2)),
        upper: Number((avg + margin).toFixed(2)),
        margin: Number(margin.toFixed(2)),
        stderr: Number(se.toFixed(2)),
        n
    };
}

// ============================================
// Effect Size
// ============================================

/**
 * Calculate Cohen's d effect size
 * 
 * @param {number[]} sample1 - First sample
 * @param {number[]} sample2 - Second sample
 * @returns {Object} Effect size with interpretation
 */
export function cohensD(sample1, sample2) {
    if (!sample1 || !sample2 || sample1.length < 2 || sample2.length < 2) {
        return { d: 0, interpretation: 'N/A' };
    }

    const mean1 = mean(sample1);
    const mean2 = mean(sample2);
    const n1 = sample1.length;
    const n2 = sample2.length;
    const var1 = variance(sample1);
    const var2 = variance(sample2);

    // Pooled standard deviation
    const pooledVar = ((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2);
    const pooledSD = Math.sqrt(pooledVar);

    // Cohen's d
    const d = (mean1 - mean2) / pooledSD;

    // Interpretation
    const absD = Math.abs(d);
    let interpretation = 'Negligible';
    if (absD >= 0.8) interpretation = 'Large';
    else if (absD >= 0.5) interpretation = 'Medium';
    else if (absD >= 0.2) interpretation = 'Small';

    return {
        d: Number(d.toFixed(3)),
        interpretation
    };
}

// ============================================
// Stability Analysis
// ============================================

/**
 * Calculate Coefficient of Variation (CV)
 * Lower CV = more stable/consistent
 * 
 * @param {number[]} data - Sample data
 * @returns {Object} CV as percentage with interpretation
 */
export function coefficientOfVariation(data) {
    if (!data || data.length < 2) {
        return { cv: 0, interpretation: 'N/A' };
    }

    const avg = mean(data);
    if (avg === 0) return { cv: Infinity, interpretation: 'Undefined' };

    const sd = stdDev(data);
    const cv = (sd / avg) * 100;

    // Interpretation
    let interpretation = 'High variability';
    if (cv < 10) interpretation = 'Very stable';
    else if (cv < 15) interpretation = 'Stable';
    else if (cv < 25) interpretation = 'Moderate variability';

    return {
        cv: Number(cv.toFixed(2)),
        interpretation
    };
}

/**
 * Simple linear regression for trend analysis
 * 
 * @param {number[]} y - Dependent variable values
 * @returns {Object} Slope, intercept, R-squared
 */
export function linearRegression(y) {
    if (!y || y.length < 2) {
        return { slope: 0, intercept: 0, rSquared: 0, hasTrend: false };
    }

    const n = y.length;
    const x = Array.from({ length: n }, (_, i) => i + 1);

    const sumX = x.reduce((a, b) => a + b, 0);
    const sumY = y.reduce((a, b) => a + b, 0);
    const sumXY = x.reduce((sum, xi, i) => sum + xi * y[i], 0);
    const sumXX = x.reduce((sum, xi) => sum + xi * xi, 0);

    const slope = (n * sumXY - sumX * sumY) / (n * sumXX - sumX * sumX);
    const intercept = (sumY - slope * sumX) / n;

    // R-squared
    const meanY = sumY / n;
    const ssTotal = y.reduce((sum, yi) => sum + (yi - meanY) ** 2, 0);
    const ssResidual = y.reduce((sum, yi, i) => {
        const predicted = slope * x[i] + intercept;
        return sum + (yi - predicted) ** 2;
    }, 0);
    const rSquared = ssTotal === 0 ? 0 : 1 - ssResidual / ssTotal;

    // Determine if there's a significant trend
    // Slope > 5% of mean per unit = notable trend
    const avgY = meanY;
    const relativeSlope = avgY === 0 ? 0 : Math.abs(slope / avgY) * 100;
    const hasTrend = relativeSlope > 5;

    return {
        slope: Number(slope.toFixed(4)),
        intercept: Number(intercept.toFixed(2)),
        rSquared: Number(rSquared.toFixed(4)),
        hasTrend,
        trendDirection: slope > 0 ? 'increasing' : slope < 0 ? 'decreasing' : 'stable'
    };
}

// ============================================
// Handover-Specific Analysis
// ============================================

/**
 * Group handovers by retry number and calculate counts
 * 
 * @param {Array} handovers - Array of handover events
 * @returns {Object} Grouped counts by retry
 */
export function groupHandoversByRetry(handovers) {
    const groups = {};

    handovers.forEach(h => {
        const retry = h.retryNumber || 1;
        if (!groups[retry]) groups[retry] = [];
        groups[retry].push(h);
    });

    return groups;
}

/**
 * Get handover counts per retry as array
 * 
 * @param {Array} handovers - Array of handover events
 * @returns {number[]} Array of counts per retry
 */
export function getCountsPerRetry(handovers) {
    const groups = groupHandoversByRetry(handovers);
    const retryNumbers = Object.keys(groups).map(Number).sort((a, b) => a - b);
    return retryNumbers.map(r => groups[r].length);
}

/**
 * Comprehensive handover statistics
 * 
 * @param {Array} mlHandovers - ML mode handovers
 * @param {Array} a3Handovers - A3 mode handovers
 * @returns {Object} Complete statistical analysis
 */
export function analyzeHandovers(mlHandovers, a3Handovers) {
    const mlCounts = getCountsPerRetry(mlHandovers);
    const a3Counts = getCountsPerRetry(a3Handovers);

    // T-test
    const tTest = welchTTest(mlCounts, a3Counts);

    // Confidence intervals
    const mlCI = confidenceInterval(mlCounts);
    const a3CI = confidenceInterval(a3Counts);

    // Effect size
    const effectSize = cohensD(mlCounts, a3Counts);

    // Stability
    const mlStability = coefficientOfVariation(mlCounts);
    const a3Stability = coefficientOfVariation(a3Counts);

    // Trend
    const mlTrend = linearRegression(mlCounts);
    const a3Trend = linearRegression(a3Counts);

    // Improvement percentage
    const improvement = a3CI.mean > 0
        ? ((a3CI.mean - mlCI.mean) / a3CI.mean * 100).toFixed(1)
        : 0;

    return {
        tTest,
        ml: {
            ci: mlCI,
            stability: mlStability,
            trend: mlTrend,
            totalHandovers: mlHandovers.length
        },
        a3: {
            ci: a3CI,
            stability: a3Stability,
            trend: a3Trend,
            totalHandovers: a3Handovers.length
        },
        effectSize,
        improvement: Number(improvement)
    };
}
