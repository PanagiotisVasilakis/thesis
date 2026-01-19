import { useState } from 'react';

export default function RetryModal({
    isOpen,
    onClose,
    onStart,
    currentMode,
    scenarioName,
    isRunning,
    currentRetry,
    totalRetries,
    onStop
}) {
    const [retryCount, setRetryCount] = useState(10);

    if (!isOpen && !isRunning) return null;

    // Show progress view when running
    // Show progress view when running
    if (isRunning) {
        const progress = totalRetries > 0 ? (currentRetry / totalRetries) * 100 : 0;

        return (
            <div className="card bg-blue-50 border-blue-200 shadow-sm animate-pulse-subtle">
                <div className="card-body py-4 flex flex-wrap items-center gap-6">
                    <div className="flex items-center gap-3 min-w-[200px]">
                        <div className="w-3 h-3 bg-blue-600 rounded-full animate-pulse"></div>
                        <h2 className="text-lg font-bold text-blue-900 m-0">
                            Running Experiment...
                        </h2>
                    </div>

                    <div className="flex-1 flex flex-col gap-1">
                        <div className="flex justify-between text-xs font-semibold text-blue-800 uppercase tracking-wider">
                            <span>Retry {currentRetry} of {totalRetries}</span>
                            <span>{Math.round(progress)}%</span>
                        </div>
                        <div className="w-full bg-blue-200 rounded-full h-2.5 overflow-hidden">
                            <div
                                className="bg-blue-600 h-full rounded-full transition-all duration-500 ease-out"
                                style={{ width: `${progress}%` }}
                            ></div>
                        </div>
                    </div>

                    <div className="flex items-center gap-4 text-sm font-medium text-blue-800">
                        <div className="flex items-center gap-2 px-3 py-1 bg-blue-100 rounded-lg">
                            <span>Mode: {currentMode ? 'ML' : 'A3'}</span>
                        </div>
                        <button
                            onClick={onStop}
                            className="btn btn-danger btn-sm whitespace-nowrap px-4"
                        >
                            ⏹️ Stop
                        </button>
                    </div>
                </div>
            </div>
        );
    }

    // Show configuration modal when not running
    return (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center" style={{ zIndex: 9999 }}>
            <div className="bg-white rounded-lg shadow-xl p-6 w-96">
                <h2 className="text-lg font-bold mb-4">🔁 Run Automated Retries</h2>

                <div className="space-y-4">
                    <p className="text-sm text-gray-600">
                        This will run the current scenario multiple times from the starting
                        position for statistical analysis. Data will be <strong>appended</strong> to
                        existing history.
                    </p>

                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                            Number of retries:
                        </label>
                        <input
                            type="number"
                            min="1"
                            max="50"
                            value={retryCount}
                            onChange={(e) => setRetryCount(Math.max(1, Math.min(50, parseInt(e.target.value) || 1)))}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                        />
                    </div>

                    <div className="bg-gray-50 rounded-lg p-3 text-sm">
                        <div className="flex justify-between">
                            <span className="text-gray-500">Mode:</span>
                            <span className={`font-medium ${currentMode ? 'text-green-600' : 'text-yellow-600'}`}>
                                {currentMode ? 'ML ✓' : 'A3'}
                            </span>
                        </div>
                    </div>

                    <div className="flex gap-3">
                        <button
                            onClick={onClose}
                            className="flex-1 btn btn-outline"
                        >
                            Cancel
                        </button>
                        <button
                            onClick={() => onStart(retryCount)}
                            className="flex-1 btn btn-primary"
                        >
                            ▶️ Start Experiment
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
