export default function ModeToggle({ mlMode, onModeChange, enabled, onChange, disabled }) {
    // Support both old and new prop patterns
    const isML = enabled !== undefined ? enabled : mlMode;
    const handleChange = onChange || onModeChange;

    return (
        <div className="card flex-1">
            <div className="card-header bg-gray-100 text-gray-900 font-bold text-lg">
                🧠 ML Handover Control
            </div>
            <div className="card-body">
                <div className="flex items-center justify-between">
                    <div>
                        <span className="font-medium">Handover Mode:</span>
                        <span className={`badge ml-2 ${isML ? 'badge-success' : 'badge-warning'}`}>
                            {isML ? 'ML Active' : 'A3 Rule'}
                        </span>
                    </div>
                    <div className="flex gap-2">
                        <button
                            onClick={() => handleChange(true)}
                            disabled={disabled}
                            className={`btn ${isML ? 'btn-success' : 'btn-outline'} ${disabled ? 'opacity-50' : ''}`}
                        >
                            🧠 ML
                        </button>
                        <button
                            onClick={() => handleChange(false)}
                            disabled={disabled}
                            className={`btn ${!isML ? 'btn-warning' : 'btn-outline'} ${disabled ? 'opacity-50' : ''}`}
                        >
                            📏 A3 Rule
                        </button>
                    </div>
                </div>
                <p className="text-sm text-gray-500 mt-3">
                    <strong>ML:</strong> Trained model predictions |
                    <strong> A3:</strong> Standard 3GPP hysteresis rule
                </p>
            </div>
        </div>
    );
}

