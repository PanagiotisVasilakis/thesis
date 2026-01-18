import { useState } from 'react';
import toast from 'react-hot-toast';
import DataTable from '../../components/shared/DataTable';
import Modal from '../../components/shared/Modal';
import ConfirmDialog from '../../components/shared/ConfirmDialog';
import UEForm from '../../components/forms/UEForm';
import { createUE, updateUE, deleteUE } from '../../api/nefClient';

const columns = [
    { accessorKey: 'name', header: 'Name' },
    { accessorKey: 'supi', header: 'SUPI' },
    { accessorKey: 'ip_address_v4', header: 'IPv4' },
    {
        accessorKey: 'speed',
        header: 'Speed',
        cell: ({ getValue }) => (
            <span className={`badge ${getValue() === 'HIGH' ? 'badge-warning' : 'badge-info'}`}>
                {getValue()}
            </span>
        )
    },
    { accessorKey: 'cell_id_hex', header: 'Connected Cell' },
];

export default function UEsTab({ data, loading, onRefresh }) {
    const [modalOpen, setModalOpen] = useState(false);
    const [confirmOpen, setConfirmOpen] = useState(false);
    const [selected, setSelected] = useState(null);

    const handleCreate = () => {
        setSelected(null);
        setModalOpen(true);
    };

    const handleEdit = (ue) => {
        setSelected(ue);
        setModalOpen(true);
    };

    const handleDelete = (ue) => {
        setSelected(ue);
        setConfirmOpen(true);
    };

    const handleSubmit = async (formData) => {
        try {
            if (selected) {
                await updateUE(selected.supi, formData);
                toast.success('UE updated successfully');
            } else {
                await createUE(formData);
                toast.success('UE created successfully');
            }
            setModalOpen(false);
            onRefresh();
        } catch (error) {
            toast.error('Operation failed: ' + (error.response?.data?.detail || error.message));
        }
    };

    const handleConfirmDelete = async () => {
        try {
            await deleteUE(selected.supi);
            toast.success('UE deleted successfully');
            onRefresh();
        } catch (error) {
            toast.error('Delete failed: ' + (error.response?.data?.detail || error.message));
        }
    };

    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center">
                <h2 className="text-lg font-semibold">📱 User Equipment (UEs)</h2>
                <button onClick={handleCreate} className="btn btn-primary">
                    + Add UE
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
                title={selected ? 'Edit UE' : 'Create UE'}
                size="lg"
            >
                <UEForm
                    initialData={selected}
                    onSubmit={handleSubmit}
                    onCancel={() => setModalOpen(false)}
                />
            </Modal>

            <ConfirmDialog
                isOpen={confirmOpen}
                onClose={() => setConfirmOpen(false)}
                onConfirm={handleConfirmDelete}
                title="Delete UE"
                message={`Are you sure you want to delete "${selected?.name}" (${selected?.supi})?`}
            />
        </div>
    );
}
