import { NavLink } from 'react-router-dom';

const navItems = [
    { path: '/dashboard', icon: '🏠', label: 'Dashboard' },
    { path: '/entities', icon: '🏛️', label: 'Entities' },
    { path: '/map', icon: '🗺️', label: 'Map' },
    { path: '/import', icon: '📥', label: 'Import' },
    { path: '/export', icon: '📤', label: 'Export' },
    { path: '/analytics', icon: '📊', label: 'Analytics' },
];

export default function Sidebar() {
    return (
        <aside className="w-64 bg-gray-900 text-white flex flex-col">
            {/* Logo */}
            <div className="p-4 border-b border-gray-700">
                <h1 className="text-2xl font-bold">
                    <span className="text-blue-400">Kinisis</span>
                </h1>
                <p className="text-xs text-gray-400 mt-1">5G Network Visualization</p>
            </div>

            {/* Navigation */}
            <nav className="flex-1 p-4">
                <ul className="space-y-2">
                    {navItems.map((item) => (
                        <li key={item.path}>
                            <NavLink
                                to={item.path}
                                className={({ isActive }) =>
                                    `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive
                                        ? 'bg-blue-600 text-white'
                                        : 'text-gray-300 hover:bg-gray-800'
                                    }`
                                }
                            >
                                <span className="text-xl">{item.icon}</span>
                                <span>{item.label}</span>
                            </NavLink>
                        </li>
                    ))}
                </ul>
            </nav>

            {/* Footer */}
            <div className="p-4 border-t border-gray-700 text-xs text-gray-500">
                <p>NEF Emulator UI</p>
                <p>Thesis Project 2026</p>
            </div>
        </aside>
    );
}
