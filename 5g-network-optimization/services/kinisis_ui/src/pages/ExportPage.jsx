import { useState } from 'react';
import { exportScenario } from '../api/nefClient';

export default function ExportPage() {
    const [jsonText, setJsonText] = useState('');
    const [loading, setLoading] = useState(false);
    const [message, setMessage] = useState(null);

    const handleExport = async () => {
        setLoading(true);
        try {
            const res = await exportScenario();
            setJsonText(JSON.stringify(res.data, null, 2));
            setMessage({ type: 'success', text: 'Scenario exported successfully!' });
        } catch (error) {
            setMessage({ type: 'error', text: 'Export failed: ' + error.message });
        } finally {
            setLoading(false);
        }
    };

    const handleCopy = () => {
        navigator.clipboard.writeText(jsonText);
        setMessage({ type: 'success', text: 'Copied to clipboard!' });
    };

    const handleDownload = () => {
        const blob = new Blob([jsonText], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `scenario_${new Date().toISOString().split('T')[0]}.json`;
        a.click();
        URL.revokeObjectURL(url);
    };

    return (
        <div className="space-y-6">
            <div>
                <h1 className="text-2xl font-bold text-gray-800">Export Scenario</h1>
                <p className="text-gray-500">Save your current network configuration</p>
            </div>

            {/* Info */}
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-blue-800">
                📤 Export your current gNBs, Cells, UEs, and Paths as a JSON file
                that can be imported later or shared.
            </div>

            {/* Message */}
            {message && (
                <div className={`p-4 rounded-lg ${message.type === 'success' ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'
                    }`}>
                    {message.text}
                </div>
            )}

            {/* Export Button */}
            <div className="card">
                <div className="card-header">Actions</div>
                <div className="card-body">
                    <button
                        onClick={handleExport}
                        disabled={loading}
                        className="btn btn-primary"
                    >
                        {loading ? 'Exporting...' : '📤 Export Current Scenario'}
                    </button>
                </div>
            </div>

            {/* JSON Display */}
            {jsonText && (
                <div className="card">
                    <div className="card-header flex justify-between items-center">
                        <span>Exported JSON</span>
                        <div className="flex gap-2">
                            <button onClick={handleCopy} className="btn btn-outline text-sm">
                                📋 Copy
                            </button>
                            <button onClick={handleDownload} className="btn btn-success text-sm">
                                💾 Download
                            </button>
                        </div>
                    </div>
                    <div className="card-body">
                        <textarea
                            value={jsonText}
                            readOnly
                            className="w-full h-64 font-mono text-sm p-4 border rounded-lg bg-gray-50"
                        />
                    </div>
                </div>
            )}
        </div>
    );
}
