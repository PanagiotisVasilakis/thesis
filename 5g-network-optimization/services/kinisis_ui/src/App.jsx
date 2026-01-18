import { Routes, Route, Navigate } from 'react-router-dom';
import { useState, useEffect } from 'react';
import ErrorBoundary from './components/shared/ErrorBoundary';
import Sidebar from './components/Layout/Sidebar';
import Header from './components/Layout/Header';
import Dashboard from './pages/Dashboard';
import MapPage from './pages/MapPage';
import ImportPage from './pages/ImportPage';
import ExportPage from './pages/ExportPage';
import AnalyticsPage from './pages/AnalyticsPage';
import LoginPage from './pages/LoginPage';
import EntitiesPage from './pages/entities/EntitiesPage';

function App() {
    const [isAuthenticated, setIsAuthenticated] = useState(false);

    useEffect(() => {
        const token = localStorage.getItem('access_token');
        setIsAuthenticated(!!token);
    }, []);

    if (!isAuthenticated) {
        return <LoginPage onLogin={() => setIsAuthenticated(true)} />;
    }

    return (
        <ErrorBoundary>
            <div className="flex min-h-screen bg-gray-100">
                <Sidebar />
                <div className="flex-1 flex flex-col">
                    <Header onLogout={() => {
                        localStorage.removeItem('access_token');
                        setIsAuthenticated(false);
                    }} />
                    <main className="flex-1 p-6 overflow-auto">
                        <Routes>
                            <Route path="/" element={<Dashboard />} />
                            <Route path="/dashboard" element={<Dashboard />} />
                            <Route path="/entities" element={<EntitiesPage />} />
                            <Route path="/map" element={<MapPage />} />
                            <Route path="/import" element={<ImportPage />} />
                            <Route path="/export" element={<ExportPage />} />
                            <Route path="/analytics" element={<AnalyticsPage />} />
                            <Route path="*" element={<Navigate to="/" replace />} />
                        </Routes>
                    </main>
                </div>
            </div>
        </ErrorBoundary>
    );
}

export default App;
