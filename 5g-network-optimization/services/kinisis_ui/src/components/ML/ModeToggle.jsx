export default function ModeToggle({ mlMode, onModeChange }) {
    return (
        <div className="card">
            <div className="card-header bg-blue-600 text-white">
                🧠 ML Handover Control
            </div>
            <div className="card-body">
                <div className="flex items-center justify-between">
                    <div>
                        <span className="font-medium">Handover Mode:</span>
                        <span className={`badge ml-2 ${mlMode ? 'badge-success' : 'badge-warning'}`}>
                            {mlMode ? 'ML Active' : 'A3 Rule'}
                        </span>
                    </div>
                    <div className="flex gap-2">
                        <button
                            onClick={() => onModeChange(true)}
                            className={`btn ${mlMode ? 'btn-success' : 'btn-outline'}`}
                        >
                            🧠 ML
                        </button>
                        <button
                            onClick={() => onModeChange(false)}
                            className={`btn ${!mlMode ? 'btn-warning' : 'btn-outline'}`}
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
