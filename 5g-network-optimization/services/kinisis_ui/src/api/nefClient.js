import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || '/api/v1';

// Create axios instance
const api = axios.create({
    baseURL: API_URL,
    headers: {
        'Content-Type': 'application/json',
    },
});

// Add auth token to requests
api.interceptors.request.use((config) => {
    const token = localStorage.getItem('access_token');
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

// Handle 401 errors
api.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error.response?.status === 401) {
            localStorage.removeItem('access_token');
            window.location.href = '/login';
        }
        return Promise.reject(error);
    }
);

// Auth
export const login = async (username, password) => {
    const formData = new URLSearchParams();
    formData.append('username', username);
    formData.append('password', password);
    const response = await api.post('/login/access-token', formData, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
    return response.data;
};

// gNBs
export const getGNBs = () => api.get('/gNBs');
export const createGNB = (data) => api.post('/gNBs', data);
export const updateGNB = (id, data) => api.put(`/gNBs/${id}`, data);
export const deleteGNB = (id) => api.delete(`/gNBs/${id}`);

// Cells
export const getCells = () => api.get('/Cells');
export const createCell = (data) => api.post('/Cells', data);
export const updateCell = (id, data) => api.put(`/Cells/${id}`, data);
export const deleteCell = (id) => api.delete(`/Cells/${id}`);

// UEs
export const getUEs = () => api.get('/UEs');
export const createUE = (data) => api.post('/UEs', data);
export const updateUE = (id, data) => api.put(`/UEs/${id}`, data);
export const deleteUE = (id) => api.delete(`/UEs/${id}`);
export const getMovingUEs = () => api.get('/UEs/movement');

// Paths
export const getPaths = () => api.get('/paths');
export const createPath = (data) => api.post('/paths', data);
export const updatePath = (id, data) => api.put(`/paths/${id}`, data);
export const deletePath = (id) => api.delete(`/paths/${id}`);

// Movement
export const startUE = (supi) => api.post(`/UEs/movement/start/${supi}`);
export const stopUE = (supi) => api.post(`/UEs/movement/stop/${supi}`);
export const startAllUEs = () => api.post('/UEs/movement/start-all');
export const stopAllUEs = () => api.post('/UEs/movement/stop-all');

// Scenarios
export const importScenario = (data) => api.post('/utils/import/scenario', data);
export const exportScenario = () => api.get('/utils/export/scenario');

export default api;
