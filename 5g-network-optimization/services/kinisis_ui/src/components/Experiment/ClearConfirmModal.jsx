export default function ClearConfirmModal({ isOpen, onClose, onConfirm, eventCount }) {
    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center" style={{ zIndex: 9999 }}>
            <div className="bg-white rounded-lg shadow-xl p-6 w-96">
                <h2 className="text-lg font-bold mb-4 text-red-600">⚠️ Clear All Data?</h2>

                <div className="space-y-4">
                    <p className="text-sm text-gray-600">
                        This will permanently delete:
                    </p>

                    <ul className="list-disc list-inside text-sm text-gray-700 space-y-1">
                        <li>All handover history ({eventCount} events)</li>
                        <li>All real-time metrics</li>
                        <li>All statistical summaries</li>
                        <li>All analytics data</li>
                    </ul>

                    <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
                        ⚠️ This action cannot be undone.
                    </div>

                    <div className="flex gap-3">
                        <button
                            onClick={onClose}
                            className="flex-1 btn btn-outline"
                        >
                            Cancel
                        </button>
                        <button
                            onClick={() => {
                                onConfirm();
                                onClose();
                            }}
                            className="flex-1 btn btn-danger bg-red-600 text-white hover:bg-red-700"
                        >
                            🗑️ Clear All
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
