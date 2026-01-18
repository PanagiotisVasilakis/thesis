import { useState } from 'react';

const tooltips = {
    gnbs: {
        title: 'gNB (Next Generation Node B)',
        description: 'The 5G base station that provides radio coverage and connects UEs to the core network.',
    },
    cells: {
        title: 'Cell',
        description: 'A coverage area served by a gNB. Each cell handles radio communication with UEs in its area.',
    },
    ues: {
        title: 'UE (User Equipment)',
        description: 'Mobile devices like smartphones or IoT devices that connect to the 5G network.',
    },
    paths: {
        title: 'Path',
        description: 'Predefined trajectory for UEs to simulate movement patterns (e.g., highway, campus walk).',
    },
};

function Tooltip({ title, description }) {
    return (
        <div className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 w-64 bg-gray-900 text-white text-xs rounded-lg p-3 shadow-lg opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10">
            <div className="font-semibold mb-1">{title}</div>
            <div className="text-gray-300">{description}</div>
            <div className="absolute top-full left-1/2 transform -translate-x-1/2 border-4 border-transparent border-t-gray-900"></div>
        </div>
    );
}

export default function StatsCards({ stats, loading }) {
    const cards = [
        {
            label: 'gNBs',
            sublabel: 'Base Stations',
            value: stats.gnbs,
            color: 'blue',
            icon: '📡',
            tooltip: 'gnbs'
        },
        {
            label: 'Cells',
            sublabel: 'Coverage Areas',
            value: stats.cells,
            color: 'cyan',
            icon: '📶',
            tooltip: 'cells'
        },
        {
            label: 'UEs',
            sublabel: 'Mobile Devices',
            value: stats.ues,
            color: 'amber',
            icon: '📱',
            tooltip: 'ues'
        },
        {
            label: 'Paths',
            sublabel: 'Trajectories',
            value: stats.paths,
            color: 'rose',
            icon: '🛤️',
            tooltip: 'paths'
        },
    ];

    const colorClasses = {
        blue: 'bg-blue-500',
        cyan: 'bg-cyan-500',
        amber: 'bg-amber-500',
        rose: 'bg-rose-500',
    };

    return (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {cards.map((card) => (
                <div
                    key={card.label}
                    className={`${colorClasses[card.color]} text-white rounded-lg p-4 shadow-md relative group cursor-help`}
                >
                    <Tooltip {...tooltips[card.tooltip]} />

                    <div className="flex justify-between items-start">
                        <span className="text-2xl">{card.icon}</span>
                        <span className="text-3xl font-bold">
                            {loading ? '-' : card.value}
                        </span>
                    </div>
                    <div className="mt-2">
                        <p className="font-medium">{card.label}</p>
                        <p className="text-sm opacity-75">{card.sublabel}</p>
                    </div>
                </div>
            ))}
        </div>
    );
}
