import { useState } from 'react';
import { importScenario } from '../api/nefClient';

const SCENARIOS = [
    { id: 'ncsrd_campus', name: '🏛️ NCSRD Campus', desc: '4 cells, 3 UEs - Basic demo' },
    { id: 'handover_stress', name: '🔥 Handover Stress', desc: '6 cells, 5 UEs - ML accuracy' },
    { id: 'highway', name: '🚗 Highway', desc: '4 cells, 6 UEs - High-speed' },
    { id: 'urban_dense', name: '🏙️ Urban Dense', desc: '8 cells, 10 UEs - Load balancing' },
];

export default function ImportPage() {
    const [selectedScenario, setSelectedScenario] = useState('');
    const [jsonText, setJsonText] = useState('');
    const [loading, setLoading] = useState(false);
    const [message, setMessage] = useState(null);

    const loadScenario = async () => {
        if (!selectedScenario) return;
        setLoading(true);
        try {
            const res = await fetch(`/static/scenarios/${selectedScenario}.json`);
            const data = await res.json();
            setJsonText(JSON.stringify(data, null, 2));
            setMessage({ type: 'success', text: 'Scenario loaded! Click Import to apply.' });
        } catch (error) {
            setMessage({ type: 'error', text: 'Failed to load scenario' });
        } finally {
            setLoading(false);
        }
    };

    const handleImport = async () => {
        if (!jsonText.trim()) {
            setMessage({ type: 'error', text: 'Please enter JSON data' });
            return;
        }
        setLoading(true);
        try {
            const data = JSON.parse(jsonText);
            await importScenario(data);
            setMessage({ type: 'success', text: 'Scenario imported successfully!' });
        } catch (error) {
            setMessage({ type: 'error', text: 'Import failed: ' + error.message });
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="space-y-6">
            <div>
                <h1 className="text-2xl font-bold text-gray-800">Import Scenario</h1>
                <p className="text-gray-500">Load a pre-built or custom scenario</p>
            </div>

            {/* Scenario Selector */}
            <div className="card">
                <div className="card-header bg-blue-600 text-white">
                    📁 Pre-built Test Scenarios
                </div>
                <div className="card-body">
                    <div className="flex gap-4 items-end">
                        <div className="flex-1">
                            <label className="block text-sm font-medium text-gray-700 mb-2">
                                Select Scenario
                            </label>
                            <select
                                value={selectedScenario}
                                onChange={(e) => setSelectedScenario(e.target.value)}
                                className="w-full px-4 py-2 border rounded-lg"
                            >
                                <option value="">-- Choose a scenario --</option>
                                {SCENARIOS.map((s) => (
                                    <option key={s.id} value={s.id}>
                                        {s.name} - {s.desc}
                                    </option>
                                ))}
                            </select>
                        </div>
                        <button
                            onClick={loadScenario}
                            disabled={!selectedScenario || loading}
                            className="btn btn-primary"
                        >
                            📥 Load
                        </button>
                    </div>
                </div>
            </div>

            {/* Warning */}
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-yellow-800">
                ⚠️ <strong>Important:</strong> For best results, ensure your database is empty before importing.
                Run <code className="bg-yellow-100 px-1 rounded">make db-reset</code> if you have console access.
            </div>

            {/* Message */}
            {message && (
                <div className={`p-4 rounded-lg ${message.type === 'success' ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'
                    }`}>
                    {message.text}
                </div>
            )}

            {/* JSON Editor */}
            <div className="card">
                <div className="card-header">JSON Data</div>
                <div className="card-body">
                    <textarea
                        value={jsonText}
                        onChange={(e) => setJsonText(e.target.value)}
                        className="w-full h-64 font-mono text-sm p-4 border rounded-lg"
                        placeholder="Paste JSON scenario here or load a pre-built scenario..."
                    />
                    <div className="mt-4 flex gap-2">
                        <button
                            onClick={handleImport}
                            disabled={loading}
                            className="btn btn-success"
                        >
                            {loading ? 'Importing...' : '⬆️ Import Scenario'}
                        </button>
                        <button
                            onClick={() => setJsonText('')}
                            className="btn btn-outline"
                        >
                            🗑️ Clear
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
