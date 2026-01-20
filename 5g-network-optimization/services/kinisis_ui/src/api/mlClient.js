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

// ML Mode - supports both new 3-mode API and legacy boolean
export const getMode = () => mlApi.get('/mode');
export const setMode = (modeOrBoolean) => {
    // Support both new mode string ("ml", "a3", "hybrid") and legacy boolean
    if (typeof modeOrBoolean === 'boolean') {
        // Legacy: true = hybrid, false = a3
        return mlApi.post('/mode', { mode: modeOrBoolean ? 'hybrid' : 'a3' });
    }
    // New: pass mode directly
    return mlApi.post('/mode', { mode: modeOrBoolean });
};

// UE Feature Vector (signal quality)
export const getUEState = (ueId) => mlApi.get(`/state/${ueId}`);

// Trigger handover
export const triggerHandover = (ueId) => mlApi.post(`/handover?ue_id=${ueId}`);

export default mlApi;
