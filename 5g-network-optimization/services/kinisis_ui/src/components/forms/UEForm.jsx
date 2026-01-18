import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';

const ueSchema = z.object({
    name: z.string().min(1, 'Name is required'),
    supi: z.string().length(15, 'SUPI must be 15 digits'),
    description: z.string().optional(),
    ip_address_v4: z.string().regex(/^(?:\d{1,3}\.){3}\d{1,3}$/, 'Invalid IPv4 address'),
    ip_address_v6: z.string().optional(),
    mac_address: z.string().regex(/^([0-9A-Fa-f]{2}-){5}[0-9A-Fa-f]{2}$/, 'Invalid MAC (XX-XX-XX-XX-XX-XX)'),
    dnn: z.string().optional(),
    mcc: z.coerce.number().min(100).max(999, 'MCC must be 3 digits'),
    mnc: z.coerce.number().min(1).max(999),
    external_identifier: z.string().optional(),
    speed: z.enum(['LOW', 'HIGH']),
});

export default function UEForm({ onSubmit, onCancel, initialData = null }) {
    const {
        register,
        handleSubmit,
        formState: { errors, isSubmitting },
    } = useForm({
        resolver: zodResolver(ueSchema),
        defaultValues: initialData || {
            name: '',
            supi: '202010000000001',
            description: 'Mobile device',
            ip_address_v4: '10.0.0.1',
            ip_address_v6: '::1',
            mac_address: '22-00-00-00-00-01',
            dnn: 'default.mnc01.mcc202.gprs',
            mcc: 202,
            mnc: 1,
            external_identifier: '',
            speed: 'LOW',
        },
    });

    return (
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Name *</label>
                    <input
                        type="text"
                        {...register('name')}
                        className={`w-full px-3 py-2 border rounded-lg ${errors.name ? 'border-red-500' : 'border-gray-300'}`}
                        placeholder="UE1"
                    />
                    {errors.name && <p className="text-red-500 text-sm mt-1">{errors.name.message}</p>}
                </div>

                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">SUPI *</label>
                    <input
                        type="text"
                        {...register('supi')}
                        className={`w-full px-3 py-2 border rounded-lg ${errors.supi ? 'border-red-500' : 'border-gray-300'}`}
                        placeholder="202010000000001"
                        disabled={!!initialData}
                    />
                    {errors.supi && <p className="text-red-500 text-sm mt-1">{errors.supi.message}</p>}
                </div>
            </div>

            <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                <input type="text" {...register('description')} className="w-full px-3 py-2 border border-gray-300 rounded-lg" />
            </div>

            <div className="grid grid-cols-2 gap-4">
                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">IPv4 Address *</label>
                    <input
                        type="text"
                        {...register('ip_address_v4')}
                        className={`w-full px-3 py-2 border rounded-lg ${errors.ip_address_v4 ? 'border-red-500' : 'border-gray-300'}`}
                        placeholder="10.0.0.1"
                    />
                    {errors.ip_address_v4 && <p className="text-red-500 text-sm mt-1">{errors.ip_address_v4.message}</p>}
                </div>

                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">MAC Address *</label>
                    <input
                        type="text"
                        {...register('mac_address')}
                        className={`w-full px-3 py-2 border rounded-lg ${errors.mac_address ? 'border-red-500' : 'border-gray-300'}`}
                        placeholder="22-00-00-00-00-01"
                    />
                    {errors.mac_address && <p className="text-red-500 text-sm mt-1">{errors.mac_address.message}</p>}
                </div>
            </div>

            <div className="grid grid-cols-3 gap-4">
                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">MCC *</label>
                    <input
                        type="number"
                        {...register('mcc')}
                        className={`w-full px-3 py-2 border rounded-lg ${errors.mcc ? 'border-red-500' : 'border-gray-300'}`}
                    />
                </div>
                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">MNC *</label>
                    <input
                        type="number"
                        {...register('mnc')}
                        className={`w-full px-3 py-2 border rounded-lg ${errors.mnc ? 'border-red-500' : 'border-gray-300'}`}
                    />
                </div>
                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Speed *</label>
                    <select {...register('speed')} className="w-full px-3 py-2 border border-gray-300 rounded-lg">
                        <option value="LOW">LOW</option>
                        <option value="HIGH">HIGH</option>
                    </select>
                </div>
            </div>

            <div className="flex justify-end gap-3 pt-4">
                <button type="button" onClick={onCancel} className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50">
                    Cancel
                </button>
                <button type="submit" disabled={isSubmitting} className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
                    {isSubmitting ? 'Saving...' : initialData ? 'Update' : 'Create'}
                </button>
            </div>
        </form>
    );
}
