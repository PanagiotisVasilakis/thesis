import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

export default function ComparisonChart({ mlCount, a3Count }) {
    const data = [
        { name: 'ML Predictions', value: mlCount, fill: '#22c55e' },
        { name: 'A3 Fallbacks', value: a3Count, fill: '#f59e0b' },
    ];

    return (
        <ResponsiveContainer width="100%" height={250}>
            <BarChart data={data}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" />
                <YAxis />
                <Tooltip />
                <Bar dataKey="value" />
            </BarChart>
        </ResponsiveContainer>
    );
}
