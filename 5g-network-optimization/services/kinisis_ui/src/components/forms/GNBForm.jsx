import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';

const gnbSchema = z.object({
    name: z.string().min(1, 'Name is required'),
    gNB_id: z.string().min(1, 'gNB ID is required').regex(/^[A-Z0-9]+$/, 'Only uppercase letters and numbers'),
    description: z.string().optional(),
    location: z.string().optional(),
});

export default function GNBForm({ onSubmit, onCancel, initialData = null }) {
    const {
        register,
        handleSubmit,
        formState: { errors, isSubmitting },
    } = useForm({
        resolver: zodResolver(gnbSchema),
        defaultValues: initialData || {
            name: '',
            gNB_id: '',
            description: '',
            location: '',
        },
    });

    return (
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                    Name <span className="text-red-500">*</span>
                </label>
                <input
                    type="text"
                    {...register('name')}
                    className={`w-full px-3 py-2 border rounded-lg ${errors.name ? 'border-red-500' : 'border-gray-300'}`}
                    placeholder="gNB1"
                />
                {errors.name && <p className="text-red-500 text-sm mt-1">{errors.name.message}</p>}
            </div>

            <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                    gNB ID <span className="text-red-500">*</span>
                </label>
                <input
                    type="text"
                    {...register('gNB_id')}
                    className={`w-full px-3 py-2 border rounded-lg ${errors.gNB_id ? 'border-red-500' : 'border-gray-300'}`}
                    placeholder="AAAAA1"
                    disabled={!!initialData}
                />
                {errors.gNB_id && <p className="text-red-500 text-sm mt-1">{errors.gNB_id.message}</p>}
            </div>

            <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                <input
                    type="text"
                    {...register('description')}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    placeholder="Base station description"
                />
            </div>

            <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Location</label>
                <input
                    type="text"
                    {...register('location')}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    placeholder="Campus, Highway, etc."
                />
            </div>

            <div className="flex justify-end gap-3 pt-4">
                <button
                    type="button"
                    onClick={onCancel}
                    className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50"
                >
                    Cancel
                </button>
                <button
                    type="submit"
                    disabled={isSubmitting}
                    className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                >
                    {isSubmitting ? 'Saving...' : initialData ? 'Update' : 'Create'}
                </button>
            </div>
        </form>
    );
}
