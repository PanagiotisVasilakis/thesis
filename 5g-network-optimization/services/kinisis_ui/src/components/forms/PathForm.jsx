import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';

const pathSchema = z.object({
    description: z.string().min(1, 'Description is required'),
    color: z.string().regex(/^#[0-9A-Fa-f]{6}$/, 'Invalid hex color'),
    start_lat: z.coerce.number().min(-90).max(90),
    start_lng: z.coerce.number().min(-180).max(180),
    end_lat: z.coerce.number().min(-90).max(90),
    end_lng: z.coerce.number().min(-180).max(180),
});

export default function PathForm({ onSubmit, onCancel, initialData = null }) {
    const {
        register,
        handleSubmit,
        formState: { errors, isSubmitting },
    } = useForm({
        resolver: zodResolver(pathSchema),
        defaultValues: initialData ? {
            description: initialData.description,
            color: initialData.color || '#00a3cc',
            start_lat: initialData.start_point?.latitude || 37.997,
            start_lng: initialData.start_point?.longitude || 23.819,
            end_lat: initialData.end_point?.latitude || 37.998,
            end_lng: initialData.end_point?.longitude || 23.820,
        } : {
            description: '',
            color: '#00a3cc',
            start_lat: 37.997,
            start_lng: 23.819,
            end_lat: 37.998,
            end_lng: 23.820,
        },
    });

    const handleFormSubmit = (data) => {
        // Transform to API format
        const pathData = {
            description: data.description,
            color: data.color,
            start_point: { latitude: data.start_lat, longitude: data.start_lng },
            end_point: { latitude: data.end_lat, longitude: data.end_lng },
            points: [
                { latitude: data.start_lat, longitude: data.start_lng },
                { latitude: data.end_lat, longitude: data.end_lng },
            ],
        };
        onSubmit(pathData);
    };

    return (
        <form onSubmit={handleSubmit(handleFormSubmit)} className="space-y-4">
            <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Description *</label>
                <input
                    type="text"
                    {...register('description')}
                    className={`w-full px-3 py-2 border rounded-lg ${errors.description ? 'border-red-500' : 'border-gray-300'}`}
                    placeholder="Path description"
                />
                {errors.description && <p className="text-red-500 text-sm mt-1">{errors.description.message}</p>}
            </div>

            <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Color *</label>
                <div className="flex gap-2 items-center">
                    <input type="color" {...register('color')} className="w-12 h-10 border rounded cursor-pointer" />
                    <input
                        type="text"
                        {...register('color')}
                        className={`flex-1 px-3 py-2 border rounded-lg ${errors.color ? 'border-red-500' : 'border-gray-300'}`}
                        placeholder="#00a3cc"
                    />
                </div>
                {errors.color && <p className="text-red-500 text-sm mt-1">{errors.color.message}</p>}
            </div>

            <div className="border rounded-lg p-4 bg-gray-50">
                <h4 className="font-medium mb-3">📍 Start Point</h4>
                <div className="grid grid-cols-2 gap-4">
                    <div>
                        <label className="block text-sm text-gray-600 mb-1">Latitude</label>
                        <input
                            type="number"
                            step="any"
                            {...register('start_lat')}
                            className={`w-full px-3 py-2 border rounded-lg ${errors.start_lat ? 'border-red-500' : 'border-gray-300'}`}
                        />
                    </div>
                    <div>
                        <label className="block text-sm text-gray-600 mb-1">Longitude</label>
                        <input
                            type="number"
                            step="any"
                            {...register('start_lng')}
                            className={`w-full px-3 py-2 border rounded-lg ${errors.start_lng ? 'border-red-500' : 'border-gray-300'}`}
                        />
                    </div>
                </div>
            </div>

            <div className="border rounded-lg p-4 bg-gray-50">
                <h4 className="font-medium mb-3">🏁 End Point</h4>
                <div className="grid grid-cols-2 gap-4">
                    <div>
                        <label className="block text-sm text-gray-600 mb-1">Latitude</label>
                        <input
                            type="number"
                            step="any"
                            {...register('end_lat')}
                            className={`w-full px-3 py-2 border rounded-lg ${errors.end_lat ? 'border-red-500' : 'border-gray-300'}`}
                        />
                    </div>
                    <div>
                        <label className="block text-sm text-gray-600 mb-1">Longitude</label>
                        <input
                            type="number"
                            step="any"
                            {...register('end_lng')}
                            className={`w-full px-3 py-2 border rounded-lg ${errors.end_lng ? 'border-red-500' : 'border-gray-300'}`}
                        />
                    </div>
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
