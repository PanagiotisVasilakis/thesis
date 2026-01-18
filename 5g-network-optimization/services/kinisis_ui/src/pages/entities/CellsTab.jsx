import { useState } from 'react';
import toast from 'react-hot-toast';
import DataTable from '../../components/shared/DataTable';
import Modal from '../../components/shared/Modal';
import ConfirmDialog from '../../components/shared/ConfirmDialog';
import CellForm from '../../components/forms/CellForm';
import { createCell, updateCell, deleteCell } from '../../api/nefClient';

const columns = [
    { accessorKey: 'name', header: 'Name' },
    { accessorKey: 'cell_id', header: 'Cell ID' },
    { accessorKey: 'description', header: 'Description' },
    {
        accessorKey: 'latitude',
        header: 'Lat/Lng',
        cell: ({ row }) => `${row.original.latitude?.toFixed(4)}, ${row.original.longitude?.toFixed(4)}`
    },
    { accessorKey: 'radius', header: 'Radius (m)' },
];

export default function CellsTab({ data, gnbs, loading, onRefresh }) {
    const [modalOpen, setModalOpen] = useState(false);
    const [confirmOpen, setConfirmOpen] = useState(false);
    const [selected, setSelected] = useState(null);

    const handleCreate = () => {
        setSelected(null);
        setModalOpen(true);
    };

    const handleEdit = (cell) => {
        setSelected(cell);
        setModalOpen(true);
    };

    const handleDelete = (cell) => {
        setSelected(cell);
        setConfirmOpen(true);
    };

    const handleSubmit = async (formData) => {
        try {
            if (selected) {
                await updateCell(selected.id, formData);
                toast.success('Cell updated successfully');
            } else {
                await createCell(formData);
                toast.success('Cell created successfully');
            }
            setModalOpen(false);
            onRefresh();
        } catch (error) {
            toast.error('Operation failed: ' + (error.response?.data?.detail || error.message));
        }
    };

    const handleConfirmDelete = async () => {
        try {
            await deleteCell(selected.id);
            toast.success('Cell deleted successfully');
            onRefresh();
        } catch (error) {
            toast.error('Delete failed: ' + (error.response?.data?.detail || error.message));
        }
    };

    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center">
                <h2 className="text-lg font-semibold">📶 Cells</h2>
                <button onClick={handleCreate} className="btn btn-primary">
                    + Add Cell
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
                title={selected ? 'Edit Cell' : 'Create Cell'}
                size="lg"
            >
                <CellForm
                    initialData={selected}
                    gnbs={gnbs}
                    onSubmit={handleSubmit}
                    onCancel={() => setModalOpen(false)}
                />
            </Modal>

            <ConfirmDialog
                isOpen={confirmOpen}
                onClose={() => setConfirmOpen(false)}
                onConfirm={handleConfirmDelete}
                title="Delete Cell"
                message={`Are you sure you want to delete "${selected?.name}"?`}
            />
        </div>
    );
}
