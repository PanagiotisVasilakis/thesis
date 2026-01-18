import { useState, useEffect } from 'react';
import { getGNBs, getCells, getUEs, getPaths } from '../api/nefClient';
import StatsCards from '../components/Dashboard/StatsCards';

export default function Dashboard() {
    const [stats, setStats] = useState({
        gnbs: 0,
        cells: 0,
        ues: 0,
        paths: 0,
    });
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchStats = async () => {
            try {
                const [gnbs, cells, ues, paths] = await Promise.all([
                    getGNBs(),
                    getCells(),
                    getUEs(),
                    getPaths(),
                ]);
                setStats({
                    gnbs: gnbs.data.length,
                    cells: cells.data.length,
                    ues: ues.data.length,
                    paths: paths.data.length,
                });
            } catch (error) {
                console.error('Failed to fetch stats:', error);
            } finally {
                setLoading(false);
            }
        };
        fetchStats();
    }, []);

    return (
        <div className="space-y-6">
            <div>
                <h1 className="text-2xl font-bold text-gray-800">Dashboard</h1>
                <p className="text-gray-500">Overview of your 5G network simulation</p>
            </div>

            {/* Welcome Panel */}
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                <h3 className="font-semibold text-blue-800 mb-2">
                    🚀 Welcome to Kinisis!
                </h3>
                <ol className="text-sm text-blue-700 list-decimal list-inside space-y-1">
                    <li>Go to <strong>Import</strong> to load a test scenario</li>
                    <li>Navigate to <strong>Map</strong> to visualize and run simulations</li>
                    <li>Toggle between ML and A3 modes to compare handover algorithms</li>
                    <li>Export results and view <strong>Analytics</strong></li>
                </ol>
            </div>

            {/* Stats Cards */}
            <StatsCards stats={stats} loading={loading} />

            {/* Quick Actions */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <a href="/import" className="card p-4 text-center hover:shadow-lg transition-shadow">
                    <span className="text-3xl">📥</span>
                    <p className="mt-2 font-medium">Load Scenario</p>
                </a>
                <a href="/map" className="card p-4 text-center hover:shadow-lg transition-shadow">
                    <span className="text-3xl">🗺️</span>
                    <p className="mt-2 font-medium">Open Map</p>
                </a>
                <a href="/analytics" className="card p-4 text-center hover:shadow-lg transition-shadow">
                    <span className="text-3xl">📊</span>
                    <p className="mt-2 font-medium">View Analytics</p>
                </a>
                <a href="/api/v1/docs" target="_blank" className="card p-4 text-center hover:shadow-lg transition-shadow">
                    <span className="text-3xl">📚</span>
                    <p className="mt-2 font-medium">API Docs</p>
                </a>
            </div>
        </div>
    );
}
