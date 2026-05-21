#!/usr/bin/env node
/**
 * Automated Experiment Runner for ML Handover Thesis
 * 
 * Runs N trials of A3 and ML modes, collects statistics, generates report.
 * 
 * Usage: 
 *   node scripts/run_experiments.js --trials=10 --duration=60 --scenario=highway
 * 
 * Arguments:
 *   --trials=N      Number of trials per mode (default: 10)
 *   --duration=N    Duration of each trial in seconds (default: 60)
 *   --scenario=X    Scenario to import (default: highway)
 *   --output=X      Output file name (auto-generated if not specified)
 * 
 * Prerequisites:
 *   - NEF backend URL exported as NEF_API
 *   - ML service URL exported as ML_API
 *   - npm install axios (run in kinisis_ui directory)
 */

const axios = require('axios');
const fs = require('fs');

// Configuration
const NEF_API = process.env.NEF_API;
const ML_API = process.env.ML_API;
if (!NEF_API || !ML_API) {
    console.error('Set NEF_API and ML_API before running experiments.');
    process.exit(1);
}

// Parse command line arguments
const args = {};
process.argv.slice(2).forEach(arg => {
    const [key, value] = arg.replace('--', '').split('=');
    args[key] = value;
});

const config = {
    trials: parseInt(args.trials || '10'),
    duration: parseInt(args.duration || '60'),
    scenario: args.scenario || 'highway',
    output: args.output || `experiment_${Date.now()}.json`,
};

// Results storage
const results = {
    timestamp: new Date().toISOString(),
    config: config,
    a3: [],
    ml: [],
    statistics: null,
};

// Axios instance with auth
let axiosInstance = null;

async function login() {
    console.log('🔐 Logging in to NEF API...');
    const username = process.env.NEF_USERNAME || process.env.FIRST_SUPERUSER;
    const password = process.env.NEF_PASSWORD || process.env.FIRST_SUPERUSER_PASSWORD;
    if (!username || !password) {
        console.error('❌ Set NEF_USERNAME/NEF_PASSWORD or FIRST_SUPERUSER/FIRST_SUPERUSER_PASSWORD');
        return false;
    }

    try {
        const res = await axios.post(`${NEF_API}/login/access-token`,
            new URLSearchParams({
                username,
                password
            }),
            { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }
        );

        axiosInstance = axios.create({
            headers: { Authorization: `Bearer ${res.data.access_token}` }
        });

        console.log('✅ Logged in successfully\n');
        return true;
    } catch (error) {
        console.error('❌ Login failed:', error.message);
        return false;
    }
}

async function importScenario(scenario) {
    console.log(`   📦 Importing scenario: ${scenario}...`);
    try {
        await axiosInstance.post(`${NEF_API}/utils/import/scenario`, { name: scenario });
        await sleep(2000); // Wait for import to complete
        return true;
    } catch (error) {
        console.error(`   ❌ Import failed: ${error.message}`);
        return false;
    }
}

async function setMode(useML) {
    const mode = useML ? 'ML' : 'A3';
    console.log(`   🔄 Setting mode to ${mode}...`);
    try {
        await axios.post(`${ML_API}/mode`, { ml_enabled: useML });
        return true;
    } catch (error) {
        console.warn(`   ⚠️ Could not set ML mode (ML service may be offline): ${error.message}`);
        return false;
    }
}

async function startAllUEs() {
    console.log('   ▶️ Starting all UEs...');
    try {
        await axiosInstance.post(`${NEF_API}/ue_movement/start-all`, {});
        return true;
    } catch (error) {
        console.error(`   ❌ Start failed: ${error.message}`);
        return false;
    }
}

async function stopAllUEs() {
    console.log('   ⏹️ Stopping all UEs...');
    try {
        await axiosInstance.post(`${NEF_API}/ue_movement/stop-all`, {});
        return true;
    } catch (error) {
        console.error(`   ❌ Stop failed: ${error.message}`);
        return false;
    }
}

async function getHandoverCount() {
    try {
        const res = await axiosInstance.get(`${NEF_API}/ue_movement/handover-stats`);
        return res.data.total_handovers || 0;
    } catch (error) {
        console.error('   ❌ handover-stats endpoint not available:', error.message);
        return null;
    }
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function runTrial(mode, trialNum) {
    const modeLabel = mode === 'ml' ? 'ML' : 'A3';
    console.log(`\n📊 Trial ${trialNum + 1}/${config.trials} [${modeLabel}]`);

    // Reset by re-importing scenario
    if (!await importScenario(config.scenario)) {
        return null;
    }

    // Set mode
    await setMode(mode === 'ml');

    // Start movement
    if (!await startAllUEs()) {
        return null;
    }

    // Wait for experiment duration
    console.log(`   ⏱️ Running for ${config.duration} seconds...`);
    const startTime = Date.now();

    // Progress indicator
    for (let i = 0; i < config.duration; i += 10) {
        await sleep(10000);
        const elapsed = Math.floor((Date.now() - startTime) / 1000);
        process.stdout.write(`\r   ⏱️ Progress: ${elapsed}/${config.duration}s`);
    }
    console.log('');

    // Stop movement
    await stopAllUEs();

    // Get handover count
    const handovers = await getHandoverCount();
    if (handovers === null) {
        console.error('   ❌ Cannot complete trial without real handover stats.');
        return null;
    }

    const result = {
        trial: trialNum + 1,
        mode: modeLabel,
        duration: config.duration,
        handovers: handovers,
        timestamp: new Date().toISOString(),
    };

    console.log(`   ✅ Completed: ${handovers} handovers recorded`);

    return result;
}

function calculateStats() {
    const mean = arr => arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0;
    const std = arr => {
        if (arr.length < 2) return 0;
        const m = mean(arr);
        return Math.sqrt(arr.reduce((acc, val) => acc + Math.pow(val - m, 2), 0) / (arr.length - 1));
    };

    const a3Counts = results.a3.map(r => r.handovers);
    const mlCounts = results.ml.map(r => r.handovers);

    const a3Mean = mean(a3Counts);
    const mlMean = mean(mlCounts);
    const a3Std = std(a3Counts);
    const mlStd = std(mlCounts);

    // Cohen's d effect size
    const pooledStd = Math.sqrt((a3Std ** 2 + mlStd ** 2) / 2);
    const cohensD = pooledStd > 0 ? (a3Mean - mlMean) / pooledStd : 0;

    // Improvement ratio
    const improvement = mlMean > 0 ? a3Mean / mlMean : Infinity;

    // Simple two-sample t-test
    const se = Math.sqrt((a3Std ** 2 / a3Counts.length) + (mlStd ** 2 / mlCounts.length));
    const tStat = se > 0 ? (a3Mean - mlMean) / se : 0;

    // Degrees of freedom (Welch's approximation)
    const df = Math.floor(
        Math.pow((a3Std ** 2 / a3Counts.length) + (mlStd ** 2 / mlCounts.length), 2) /
        (Math.pow(a3Std ** 2 / a3Counts.length, 2) / (a3Counts.length - 1) +
            Math.pow(mlStd ** 2 / mlCounts.length, 2) / (mlCounts.length - 1))
    );

    return {
        a3: { mean: a3Mean, std: a3Std, n: a3Counts.length, values: a3Counts },
        ml: { mean: mlMean, std: mlStd, n: mlCounts.length, values: mlCounts },
        improvement: improvement,
        cohensD: cohensD,
        tStatistic: tStat,
        degreesOfFreedom: df,
        // Critical t-value for 95% confidence (approximation)
        isSignificant: Math.abs(tStat) > 2.0 && a3Counts.length >= 10 && mlCounts.length >= 10,
    };
}

function printSummary(stats) {
    console.log('\n' + '='.repeat(70));
    console.log('📈 STATISTICAL SUMMARY - ML Handover Experiment');
    console.log('='.repeat(70));
    console.log('');
    console.log('CONFIGURATION:');
    console.log(`  Scenario:     ${config.scenario}`);
    console.log(`  Duration:     ${config.duration}s per trial`);
    console.log(`  Trials:       ${config.trials} per mode`);
    console.log('');
    console.log('RESULTS:');
    console.log(`  A3 Handovers: ${stats.a3.mean.toFixed(2)} ± ${stats.a3.std.toFixed(2)} (n=${stats.a3.n})`);
    console.log(`  ML Handovers: ${stats.ml.mean.toFixed(2)} ± ${stats.ml.std.toFixed(2)} (n=${stats.ml.n})`);
    console.log('');
    console.log('ANALYSIS:');
    console.log(`  Improvement:  ${stats.improvement === Infinity ? '∞' : stats.improvement.toFixed(2)}x reduction`);
    console.log(`  Cohen's d:    ${stats.cohensD.toFixed(3)} (${getEffectSizeLabel(stats.cohensD)})`);
    console.log(`  t-statistic:  ${stats.tStatistic.toFixed(3)}`);
    console.log(`  Significant:  ${stats.isSignificant ? '✅ YES (p < 0.05)' : '❌ NO (need more trials)'}`);
    console.log('');
    console.log('='.repeat(70));

    // Thesis-ready statement
    if (stats.isSignificant && stats.improvement > 1) {
        console.log('');
        console.log('📝 THESIS STATEMENT:');
        console.log(`   "The ML-based handover algorithm reduced handover frequency by`);
        console.log(`    ${((1 - 1 / stats.improvement) * 100).toFixed(1)}% compared to the A3 baseline`);
        console.log(`    (${stats.a3.mean.toFixed(1)} ± ${stats.a3.std.toFixed(1)} vs ${stats.ml.mean.toFixed(1)} ± ${stats.ml.std.toFixed(1)} handovers,`);
        console.log(`    Cohen's d = ${stats.cohensD.toFixed(2)}, p < 0.05)."`);
        console.log('');
    }
}

function getEffectSizeLabel(d) {
    const absD = Math.abs(d);
    if (absD >= 0.8) return 'Large Effect';
    if (absD >= 0.5) return 'Medium Effect';
    if (absD >= 0.2) return 'Small Effect';
    return 'Negligible';
}

async function main() {
    console.log('');
    console.log('╔════════════════════════════════════════════════════════════╗');
    console.log('║   🧪 ML Handover Experiment Runner                         ║');
    console.log('║   Thesis Statistical Validation Tool                       ║');
    console.log('╚════════════════════════════════════════════════════════════╝');
    console.log('');
    console.log(`Configuration:`);
    console.log(`  Trials:    ${config.trials} per mode`);
    console.log(`  Duration:  ${config.duration}s per trial`);
    console.log(`  Scenario:  ${config.scenario}`);
    console.log(`  Output:    ${config.output}`);
    console.log('');

    // Login
    if (!await login()) {
        console.error('Cannot proceed without authentication.');
        process.exit(1);
    }

    // Run A3 trials
    console.log('━'.repeat(50));
    console.log('🔶 PHASE 1: Running A3 (Baseline) Trials');
    console.log('━'.repeat(50));

    for (let i = 0; i < config.trials; i++) {
        const result = await runTrial('a3', i);
        if (result) {
            results.a3.push(result);
        }
    }

    // Run ML trials
    console.log('');
    console.log('━'.repeat(50));
    console.log('🟢 PHASE 2: Running ML (Proposed) Trials');
    console.log('━'.repeat(50));

    for (let i = 0; i < config.trials; i++) {
        const result = await runTrial('ml', i);
        if (result) {
            results.ml.push(result);
        }
    }

    // Calculate statistics
    results.statistics = calculateStats();

    // Save results
    fs.writeFileSync(config.output, JSON.stringify(results, null, 2));
    console.log(`\n💾 Results saved to: ${config.output}`);

    // Print summary
    printSummary(results.statistics);
}

// Run
main().catch(error => {
    console.error('Fatal error:', error);
    process.exit(1);
});
