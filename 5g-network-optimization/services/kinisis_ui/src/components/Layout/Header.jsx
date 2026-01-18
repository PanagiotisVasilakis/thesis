export default function Header({ onLogout }) {
    return (
        <header className="bg-white shadow-sm px-6 py-4 flex justify-between items-center">
            <div>
                <h2 className="text-xl font-semibold text-gray-800">
                    5G Network Emulator
                </h2>
            </div>
            <div className="flex items-center gap-4">
                <a
                    href="/api/v1/docs"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm text-gray-600 hover:text-blue-600"
                >
                    📚 API Docs
                </a>
                <button
                    onClick={onLogout}
                    className="btn btn-outline text-sm"
                >
                    🚪 Logout
                </button>
            </div>
        </header>
    );
}
