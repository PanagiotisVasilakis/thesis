import { useState, useEffect, useMemo } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, PieChart, Pie, Cell, ResponsiveContainer } from 'recharts';
import PingPongAnalysis from '../components/Analytics/PingPongAnalysis';
import StatisticalSummary from '../components/Analytics/StatisticalSummary';
import QoSComparisonChart from '../components/Analytics/QoSComparisonChart';
import ConfidenceDistribution from '../components/Analytics/ConfidenceDistribution';
import FailureModeTest from '../components/Analytics/FailureModeTest';
import ExportReport from '../components/Analytics/ExportReport';
import UETypeBreakdown from '../components/Analytics/UETypeBreakdown';
import StabilityAnalysis from '../components/Analytics/StabilityAnalysis';

export default function AnalyticsPage() {
    const [history, setHistory] = useState([]);
    const [sessions, setSessions] = useState([]);
    const [selectedSession, setSelectedSession] = useState('all');

    useEffect(() => {
        const saved = localStorage.getItem('handover_history');
        if (saved) {
            const parsed = JSON.parse(saved);
            setHistory(parsed);
            // Extract unique sessions
            const uniqueSessions = [...new Set(parsed.map(h => h.sessionId).filter(Boolean))];
            setSessions(uniqueSessions);
        }
    }, []);

    // Filter history based on selected session
    const filteredHistory = useMemo(() => {
        if (selectedSession === 'all') return history;
        return history.filter(h => h.sessionId === selectedSession);
    }, [history, selectedSession]);

    // Calculate stats from filtered history
    const stats = useMemo(() => {
        const ml = filteredHistory.filter(h => h.method === 'ML').length;
        const a3 = filteredHistory.filter(h => h.method === 'A3 Event').length;
        return { ml, a3, total: ml + a3 };
    }, [filteredHistory]);

    const resetStats = () => {
        localStorage.removeItem('handover_history');
        localStorage.removeItem('kinisis_analytics');
        setHistory([]);
        setSessions([]);
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
            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-2xl font-bold text-gray-800">📊 Analytics Dashboard</h1>
                    <p className="text-gray-500">Compare ML vs A3 handover performance</p>
                </div>

                {/* Session Filter */}
                <div className="flex items-center gap-4">
                    <label className="text-sm font-medium text-gray-600">Session:</label>
                    <select
                        value={selectedSession}
                        onChange={e => setSelectedSession(e.target.value)}
                        className="select select-bordered select-sm"
                    >
                        <option value="all">All Sessions ({sessions.length})</option>
                        {sessions.map(s => (
                            <option key={s} value={s}>
                                {s.replace('session_', '').slice(0, 8)}...
                            </option>
                        ))}
                    </select>
                </div>
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
                    <div className="text-sm text-gray-500 mt-1">ML Participation</div>
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

            {/* Advanced Analysis */}
            <div className="grid grid-cols-2 gap-4">
                <PingPongAnalysis history={filteredHistory} />
                <StatisticalSummary history={history} />
            </div>

            {/* NEW: UE Type Breakdown & Stability Analysis */}
            <div className="grid grid-cols-2 gap-4">
                <UETypeBreakdown history={filteredHistory} />
                <StabilityAnalysis history={history} />
            </div>

            {/* QoS Comparison */}
            <QoSComparisonChart history={filteredHistory} />

            {/* Confidence & Failure Testing */}
            <div className="grid grid-cols-2 gap-4">
                <ConfidenceDistribution history={filteredHistory} />
                <FailureModeTest />
            </div>

            {/* Export */}
            <ExportReport history={history} stats={stats} />

            {/* Instructions */}
            <div className="card">
                <div className="card-header">How to Run a Valid Experiment</div>
                <div className="card-body">
                    <ol className="list-decimal list-inside space-y-2 text-gray-600">
                        <li>Go to <strong>Map</strong> and click <strong>🔄 New Session</strong></li>
                        <li>Set mode to <strong>A3</strong>, run for 60 seconds, note the count</li>
                        <li>Click <strong>🔄 New Session</strong> again</li>
                        <li>Set mode to <strong>ML</strong>, run for 60 seconds, note the count</li>
                        <li>Repeat steps 1-4 at least <strong>10 times each</strong> for statistical validity</li>
                        <li>Check the <strong>Statistical Summary</strong> above for significance</li>
                    </ol>
                </div>
            </div>

            {/* Actions */}
            <div className="flex gap-4">
                <button
                    onClick={resetStats}
                    className="btn btn-outline"
                >
                    🗑️ Reset All Data
                </button>
            </div>
        </div>
    );
}
