import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || '/api/v1';

const mlApi = axios.create({
    baseURL: `${API_URL}/ml`,
    headers: { 'Content-Type': 'application/json' },
});

// Add auth token
mlApi.interceptors.request.use((config) => {
    const token = localStorage.getItem('access_token');
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

// ML Mode
export const getMode = () => mlApi.get('/mode');
export const setMode = (useML) => mlApi.post('/mode', { use_ml: useML });

// UE Feature Vector (signal quality)
export const getUEState = (ueId) => mlApi.get(`/state/${ueId}`);

// Trigger handover
export const triggerHandover = (ueId) => mlApi.post(`/handover?ue_id=${ueId}`);

export default mlApi;
