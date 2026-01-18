import { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, PieChart, Pie, Cell, ResponsiveContainer } from 'recharts';

export default function AnalyticsPage() {
    const [stats, setStats] = useState({ ml: 0, a3: 0, total: 0 });

    useEffect(() => {
        const saved = localStorage.getItem('kinisis_analytics');
        if (saved) {
            setStats(JSON.parse(saved));
        }
    }, []);

    const saveStats = (newStats) => {
        setStats(newStats);
        localStorage.setItem('kinisis_analytics', JSON.stringify(newStats));
    };

    const barData = [
        { name: 'ML Predictions', value: stats.ml, fill: '#22c55e' },
        { name: 'A3 Fallbacks', value: stats.a3, fill: '#f59e0b' },
    ];

    const pieData = [
        { name: 'ML', value: stats.ml || 1 },
        { name: 'A3', value: stats.a3 || 1 },
    ];

    const COLORS = ['#22c55e', '#f59e0b'];

    const mlPct = stats.total > 0 ? ((stats.ml / stats.total) * 100).toFixed(0) : 0;

    return (
        <div className="space-y-6">
            <div>
                <h1 className="text-2xl font-bold text-gray-800">📊 Analytics Dashboard</h1>
                <p className="text-gray-500">Compare ML vs A3 handover performance</p>
            </div>

            {/* Stats Cards */}
            <div className="grid grid-cols-4 gap-4">
                <div className="card text-center p-6">
                    <div className="text-4xl font-bold text-green-600">{stats.ml}</div>
                    <div className="text-sm text-gray-500 mt-1">ML Decisions</div>
                </div>
                <div className="card text-center p-6">
                    <div className="text-4xl font-bold text-yellow-600">{stats.a3}</div>
                    <div className="text-sm text-gray-500 mt-1">A3 Fallbacks</div>
                </div>
                <div className="card text-center p-6">
                    <div className="text-4xl font-bold text-blue-600">{stats.total}</div>
                    <div className="text-sm text-gray-500 mt-1">Total Handovers</div>
                </div>
                <div className="card text-center p-6">
                    <div className="text-4xl font-bold text-purple-600">{mlPct}%</div>
                    <div className="text-sm text-gray-500 mt-1">ML Success Rate</div>
                </div>
            </div>

            {/* Charts */}
            <div className="grid grid-cols-2 gap-4">
                <div className="card">
                    <div className="card-header">Method Comparison</div>
                    <div className="card-body h-64">
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={barData}>
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis dataKey="name" />
                                <YAxis />
                                <Tooltip />
                                <Bar dataKey="value" />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </div>

                <div className="card">
                    <div className="card-header">Distribution</div>
                    <div className="card-body h-64">
                        <ResponsiveContainer width="100%" height="100%">
                            <PieChart>
                                <Pie
                                    data={pieData}
                                    dataKey="value"
                                    nameKey="name"
                                    cx="50%"
                                    cy="50%"
                                    outerRadius={80}
                                    label
                                >
                                    {pieData.map((entry, index) => (
                                        <Cell key={`cell-${index}`} fill={COLORS[index]} />
                                    ))}
                                </Pie>
                                <Tooltip />
                                <Legend />
                            </PieChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            </div>

            {/* Instructions */}
            <div className="card">
                <div className="card-header">How to Use</div>
                <div className="card-body">
                    <ol className="list-decimal list-inside space-y-2 text-gray-600">
                        <li>Go to <strong>Import</strong> and load a test scenario</li>
                        <li>Navigate to <strong>Map</strong> and start UE movement</li>
                        <li>Toggle between ML and A3 modes to compare</li>
                        <li>Return here to view aggregated results</li>
                    </ol>
                </div>
            </div>

            {/* Actions */}
            <div className="flex gap-4">
                <button
                    onClick={() => saveStats({ ml: 0, a3: 0, total: 0 })}
                    className="btn btn-outline"
                >
                    🗑️ Reset Stats
                </button>
            </div>
        </div>
    );
}
