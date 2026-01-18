import { useState } from 'react';
import toast from 'react-hot-toast';
import DataTable from '../../components/shared/DataTable';
import Modal from '../../components/shared/Modal';
import ConfirmDialog from '../../components/shared/ConfirmDialog';
import GNBForm from '../../components/forms/GNBForm';
import { createGNB, updateGNB, deleteGNB } from '../../api/nefClient';

const columns = [
    { accessorKey: 'name', header: 'Name' },
    { accessorKey: 'gNB_id', header: 'gNB ID' },
    { accessorKey: 'description', header: 'Description' },
    { accessorKey: 'location', header: 'Location' },
];

export default function GNBsTab({ data, loading, onRefresh }) {
    const [modalOpen, setModalOpen] = useState(false);
    const [confirmOpen, setConfirmOpen] = useState(false);
    const [selected, setSelected] = useState(null);

    const handleCreate = () => {
        setSelected(null);
        setModalOpen(true);
    };

    const handleEdit = (gnb) => {
        setSelected(gnb);
        setModalOpen(true);
    };

    const handleDelete = (gnb) => {
        setSelected(gnb);
        setConfirmOpen(true);
    };

    const handleSubmit = async (formData) => {
        try {
            if (selected) {
                await updateGNB(selected.id, formData);
                toast.success('gNB updated successfully');
            } else {
                await createGNB(formData);
                toast.success('gNB created successfully');
            }
            setModalOpen(false);
            onRefresh();
        } catch (error) {
            toast.error('Operation failed: ' + (error.response?.data?.detail || error.message));
        }
    };

    const handleConfirmDelete = async () => {
        try {
            await deleteGNB(selected.id);
            toast.success('gNB deleted successfully');
            onRefresh();
        } catch (error) {
            toast.error('Delete failed: ' + (error.response?.data?.detail || error.message));
        }
    };

    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center">
                <h2 className="text-lg font-semibold">📡 Base Stations (gNBs)</h2>
                <button onClick={handleCreate} className="btn btn-primary">
                    + Add gNB
                </button>
            </div>

            <DataTable
                data={data}
                columns={columns}
                loading={loading}
                onEdit={handleEdit}
                onDelete={handleDelete}
            />

            <Modal
                isOpen={modalOpen}
                onClose={() => setModalOpen(false)}
                title={selected ? 'Edit gNB' : 'Create gNB'}
            >
                <GNBForm
                    initialData={selected}
                    onSubmit={handleSubmit}
                    onCancel={() => setModalOpen(false)}
                />
            </Modal>

            <ConfirmDialog
                isOpen={confirmOpen}
                onClose={() => setConfirmOpen(false)}
                onConfirm={handleConfirmDelete}
                title="Delete gNB"
                message={`Are you sure you want to delete "${selected?.name}"? This will also delete all associated cells.`}
            />
        </div>
    );
}
