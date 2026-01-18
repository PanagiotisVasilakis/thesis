import { useState } from 'react';
import toast from 'react-hot-toast';
import DataTable from '../../components/shared/DataTable';
import Modal from '../../components/shared/Modal';
import ConfirmDialog from '../../components/shared/ConfirmDialog';
import PathForm from '../../components/forms/PathForm';
import { createPath, updatePath, deletePath } from '../../api/nefClient';

const columns = [
    { accessorKey: 'id', header: 'ID' },
    { accessorKey: 'description', header: 'Description' },
    {
        accessorKey: 'color',
        header: 'Color',
        cell: ({ getValue }) => (
            <div className="flex items-center gap-2">
                <div
                    className="w-6 h-6 rounded border"
                    style={{ backgroundColor: getValue() }}
                />
                <span className="text-sm font-mono">{getValue()}</span>
            </div>
        )
    },
    {
        accessorKey: 'points',
        header: 'Points',
        cell: ({ getValue }) => getValue()?.length || 0
    },
];

export default function PathsTab({ data, loading, onRefresh }) {
    const [modalOpen, setModalOpen] = useState(false);
    const [confirmOpen, setConfirmOpen] = useState(false);
    const [selected, setSelected] = useState(null);

    const handleCreate = () => {
        setSelected(null);
        setModalOpen(true);
    };

    const handleEdit = (path) => {
        setSelected(path);
        setModalOpen(true);
    };

    const handleDelete = (path) => {
        setSelected(path);
        setConfirmOpen(true);
    };

    const handleSubmit = async (formData) => {
        try {
            if (selected) {
                await updatePath(selected.id, formData);
                toast.success('Path updated successfully');
            } else {
                await createPath(formData);
                toast.success('Path created successfully');
            }
            setModalOpen(false);
            onRefresh();
        } catch (error) {
            toast.error('Operation failed: ' + (error.response?.data?.detail || error.message));
        }
    };

    const handleConfirmDelete = async () => {
        try {
            await deletePath(selected.id);
            toast.success('Path deleted successfully');
            onRefresh();
        } catch (error) {
            toast.error('Delete failed: ' + (error.response?.data?.detail || error.message));
        }
    };

    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center">
                <h2 className="text-lg font-semibold">🛤️ Paths</h2>
                <button onClick={handleCreate} className="btn btn-primary">
                    + Add Path
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
                title={selected ? 'Edit Path' : 'Create Path'}
                size="lg"
            >
                <PathForm
                    initialData={selected}
                    onSubmit={handleSubmit}
                    onCancel={() => setModalOpen(false)}
                />
            </Modal>

            <ConfirmDialog
                isOpen={confirmOpen}
                onClose={() => setConfirmOpen(false)}
                onConfirm={handleConfirmDelete}
                title="Delete Path"
                message={`Are you sure you want to delete path "${selected?.description}"?`}
            />
        </div>
    );
}
