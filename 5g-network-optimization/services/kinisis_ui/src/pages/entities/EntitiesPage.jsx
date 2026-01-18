import { useState, useEffect } from 'react';
import { Tab } from '@headlessui/react';
import toast, { Toaster } from 'react-hot-toast';
import { getGNBs, getCells, getUEs, getPaths } from '../../api/nefClient';
import GNBsTab from './GNBsTab';
import CellsTab from './CellsTab';
import UEsTab from './UEsTab';
import PathsTab from './PathsTab';

const tabs = [
    { name: 'gNBs', icon: '📡' },
    { name: 'Cells', icon: '📶' },
    { name: 'UEs', icon: '📱' },
    { name: 'Paths', icon: '🛤️' },
];

export default function EntitiesPage() {
    const [gnbs, setGnbs] = useState([]);
    const [cells, setCells] = useState([]);
    const [ues, setUes] = useState([]);
    const [paths, setPaths] = useState([]);
    const [loading, setLoading] = useState(true);

    const fetchAll = async () => {
        setLoading(true);
        try {
            const [gnbsRes, cellsRes, uesRes, pathsRes] = await Promise.all([
                getGNBs(),
                getCells(),
                getUEs(),
                getPaths(),
            ]);
            setGnbs(gnbsRes.data);
            setCells(cellsRes.data);
            setUes(uesRes.data);
            setPaths(pathsRes.data);
        } catch (error) {
            toast.error('Failed to load data');
            console.error(error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchAll();
    }, []);

    return (
        <div className="space-y-6">
            <Toaster position="top-right" />

            <div>
                <h1 className="text-2xl font-bold text-gray-800">🏛️ Entity Management</h1>
                <p className="text-gray-500">Manage gNBs, Cells, UEs, and Paths</p>
            </div>

            <Tab.Group>
                <Tab.List className="flex space-x-1 rounded-xl bg-gray-100 p-1">
                    {tabs.map((tab) => (
                        <Tab
                            key={tab.name}
                            className={({ selected }) =>
                                `w-full rounded-lg py-2.5 text-sm font-medium leading-5 transition-colors
                ${selected
                                    ? 'bg-white text-blue-700 shadow'
                                    : 'text-gray-600 hover:bg-white/50 hover:text-gray-800'
                                }`
                            }
                        >
                            <span className="mr-2">{tab.icon}</span>
                            {tab.name}
                        </Tab>
                    ))}
                </Tab.List>

                <Tab.Panels className="mt-4">
                    <Tab.Panel>
                        <GNBsTab data={gnbs} loading={loading} onRefresh={fetchAll} />
                    </Tab.Panel>
                    <Tab.Panel>
                        <CellsTab data={cells} gnbs={gnbs} loading={loading} onRefresh={fetchAll} />
                    </Tab.Panel>
                    <Tab.Panel>
                        <UEsTab data={ues} loading={loading} onRefresh={fetchAll} />
                    </Tab.Panel>
                    <Tab.Panel>
                        <PathsTab data={paths} loading={loading} onRefresh={fetchAll} />
                    </Tab.Panel>
                </Tab.Panels>
            </Tab.Group>
        </div>
    );
}
