import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';

const cellSchema = z.object({
    name: z.string().min(1, 'Name is required'),
    cell_id: z.string().min(1, 'Cell ID is required'),
    gNB_id: z.coerce.number().min(1, 'Select a gNB'),
    description: z.string().optional(),
    latitude: z.coerce.number().min(-90).max(90, 'Invalid latitude (-90 to 90)'),
    longitude: z.coerce.number().min(-180).max(180, 'Invalid longitude (-180 to 180)'),
    radius: z.coerce.number().min(1).max(10000, 'Radius must be 1-10000m'),
});

export default function CellForm({ onSubmit, onCancel, initialData = null, gnbs = [] }) {
    const {
        register,
        handleSubmit,
        formState: { errors, isSubmitting },
    } = useForm({
        resolver: zodResolver(cellSchema),
        defaultValues: initialData || {
            name: '',
            cell_id: '',
            gNB_id: '',
            description: '',
            latitude: 37.997,
            longitude: 23.819,
            radius: 100,
        },
    });

    return (
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                        Name <span className="text-red-500">*</span>
                    </label>
                    <input
                        type="text"
                        {...register('name')}
                        className={`w-full px-3 py-2 border rounded-lg ${errors.name ? 'border-red-500' : 'border-gray-300'}`}
                        placeholder="Cell-1"
                    />
                    {errors.name && <p className="text-red-500 text-sm mt-1">{errors.name.message}</p>}
                </div>

                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                        Cell ID <span className="text-red-500">*</span>
                    </label>
                    <input
                        type="text"
                        {...register('cell_id')}
                        className={`w-full px-3 py-2 border rounded-lg ${errors.cell_id ? 'border-red-500' : 'border-gray-300'}`}
                        placeholder="CELL001"
                        disabled={!!initialData}
                    />
                    {errors.cell_id && <p className="text-red-500 text-sm mt-1">{errors.cell_id.message}</p>}
                </div>
            </div>

            <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                    Parent gNB <span className="text-red-500">*</span>
                </label>
                <select
                    {...register('gNB_id')}
                    className={`w-full px-3 py-2 border rounded-lg ${errors.gNB_id ? 'border-red-500' : 'border-gray-300'}`}
                >
                    <option value="">Select gNB...</option>
                    {gnbs.map((gnb) => (
                        <option key={gnb.id} value={gnb.id}>
                            {gnb.name} ({gnb.gNB_id})
                        </option>
                    ))}
                </select>
                {errors.gNB_id && <p className="text-red-500 text-sm mt-1">{errors.gNB_id.message}</p>}
            </div>

            <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                <input
                    type="text"
                    {...register('description')}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    placeholder="Coverage area description"
                />
            </div>

            <div className="grid grid-cols-3 gap-4">
                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Latitude *</label>
                    <input
                        type="number"
                        step="any"
                        {...register('latitude')}
                        className={`w-full px-3 py-2 border rounded-lg ${errors.latitude ? 'border-red-500' : 'border-gray-300'}`}
                    />
                    {errors.latitude && <p className="text-red-500 text-sm mt-1">{errors.latitude.message}</p>}
                </div>

                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Longitude *</label>
                    <input
                        type="number"
                        step="any"
                        {...register('longitude')}
                        className={`w-full px-3 py-2 border rounded-lg ${errors.longitude ? 'border-red-500' : 'border-gray-300'}`}
                    />
                    {errors.longitude && <p className="text-red-500 text-sm mt-1">{errors.longitude.message}</p>}
                </div>

                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Radius (m) *</label>
                    <input
                        type="number"
                        {...register('radius')}
                        className={`w-full px-3 py-2 border rounded-lg ${errors.radius ? 'border-red-500' : 'border-gray-300'}`}
                    />
                    {errors.radius && <p className="text-red-500 text-sm mt-1">{errors.radius.message}</p>}
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
