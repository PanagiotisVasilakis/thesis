export default function ModeToggle({ mode, onModeChange, enabled, onChange, disabled }) {
    // Support both new mode prop and legacy enabled boolean
    // mode: "ml" | "a3" | "hybrid"
    // enabled: legacy boolean (true = hybrid, false = a3)

    const currentMode = mode !== undefined
        ? mode
        : (enabled ? 'hybrid' : 'a3');

    // Handle both new and legacy callbacks
    const handleModeChange = (newMode) => {
        if (onModeChange) {
            onModeChange(newMode);
        } else if (onChange) {
            // Legacy callback expects boolean
            onChange(newMode !== 'a3');
        }
    };

    return (
        <div className="card flex-1">
            <div className="card-header bg-gray-100 text-gray-900 font-bold text-lg">
                🧠 ML Handover Control
            </div>
            <div className="card-body">
                <div className="flex items-center justify-between">
                    <div>
                        <span className="font-medium">Handover Mode:</span>
                        <span className={`badge ml-2 ${currentMode === 'ml' ? 'badge-success' :
                                currentMode === 'hybrid' ? 'badge-info' :
                                    'badge-warning'
                            }`}>
                            {currentMode === 'ml' ? 'ML Only' :
                                currentMode === 'hybrid' ? 'Hybrid' :
                                    'A3 Rule'}
                        </span>
                    </div>
                    <div className="flex gap-2">
                        <button
                            onClick={() => handleModeChange('ml')}
                            disabled={disabled}
                            className={`btn ${currentMode === 'ml' ? 'btn-success' : 'btn-outline'} ${disabled ? 'opacity-50' : ''}`}
                            title="Pure ML predictions without A3 fallback"
                        >
                            🧠 ML
                        </button>
                        <button
                            onClick={() => handleModeChange('hybrid')}
                            disabled={disabled}
                            className={`btn ${currentMode === 'hybrid' ? 'btn-primary' : 'btn-outline'} ${disabled ? 'opacity-50' : ''}`}
                            title="ML primary with A3 fallback on failures"
                        >
                            🔄 Hybrid
                        </button>
                        <button
                            onClick={() => handleModeChange('a3')}
                            disabled={disabled}
                            className={`btn ${currentMode === 'a3' ? 'btn-warning' : 'btn-outline'} ${disabled ? 'opacity-50' : ''}`}
                            title="Standard 3GPP A3 rule only"
                        >
                            📏 A3
                        </button>
                    </div>
                </div>
                <div className="mt-3 text-sm text-gray-500 space-y-1">
                    <p><strong>ML:</strong> Pure model predictions (no safety fallback)</p>
                    <p><strong>Hybrid:</strong> ML with A3 fallback on low confidence/QoS failures</p>
                    <p><strong>A3:</strong> Standard 3GPP hysteresis rule only</p>
                </div>
            </div>
        </div>
    );
}

