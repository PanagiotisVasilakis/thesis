import { createContext, useContext, useState, useRef, useCallback } from 'react';
import { startAllUEs, stopAllUEs, importScenario } from '../api/nefClient';

const ExperimentContext = createContext(null);

export function ExperimentProvider({ children }) {
    // Experiment state
    const [isRetrying, setIsRetrying] = useState(false);
    const [currentRetry, setCurrentRetry] = useState(0);
    const [totalRetries, setTotalRetries] = useState(0);
    const [isRunning, setIsRunning] = useState(false);
    const [timeRemaining, setTimeRemaining] = useState(0);
    const [sessionId, setSessionId] = useState(`session_${Date.now()}`);
    const [mlMode, setMlMode] = useState('hybrid');  // 'ml', 'a3', or 'hybrid'
    const [activeScenario, setActiveScenarioState] = useState(() => {
        try {
            const saved = localStorage.getItem('kinisis_active_scenario');
            return saved ? JSON.parse(saved) : null;
        } catch {
            localStorage.removeItem('kinisis_active_scenario');
            return null;
        }
    });
    const [duration, setDuration] = useState(60);
    const [scenarioName, setScenarioName] = useState(activeScenario?.name || '');

    const stopRetryRef = useRef(false);
    const prevUEsRef = useRef({});

    // Handover history (persisted to localStorage)
    const [handoverHistory, setHandoverHistory] = useState(() => {
        try {
            const saved = localStorage.getItem('handover_history');
            return saved ? JSON.parse(saved) : [];
        } catch {
            localStorage.removeItem('handover_history');
            return [];
        }
    });

    // Add handover to history
    const addHandover = useCallback((handover) => {
        setHandoverHistory(prev => {
            const updated = [...prev, handover];
            localStorage.setItem('handover_history', JSON.stringify(updated));
            return updated;
        });
    }, []);

    // Clear all data
    const clearAll = useCallback(() => {
        setHandoverHistory([]);
        localStorage.removeItem('handover_history');
        localStorage.removeItem('kinisis_analytics');
        setSessionId(`session_${Date.now()}`);
        prevUEsRef.current = {};
    }, []);

    const setActiveScenario = useCallback((payload, name = 'Custom scenario') => {
        const scenario = { name, payload };
        setActiveScenarioState(scenario);
        setScenarioName(name);
        localStorage.setItem('kinisis_active_scenario', JSON.stringify(scenario));
    }, []);

    const resetActiveScenario = useCallback(async () => {
        if (!activeScenario?.payload) {
            return false;
        }
        await importScenario(activeScenario.payload);
        return true;
    }, [activeScenario]);

    // Start retries
    const startRetries = useCallback(async (numRetries, onProgress) => {
        setIsRetrying(true);
        setTotalRetries(numRetries);
        setCurrentRetry(0);
        stopRetryRef.current = false;

        const batchSessionId = `session_${Date.now()}`;
        setSessionId(batchSessionId);

        for (let i = 1; i <= numRetries; i++) {
            if (stopRetryRef.current) break;

            setCurrentRetry(i);
            if (onProgress) onProgress(i, numRetries);

            try {
                if (activeScenario?.payload) {
                    await importScenario(activeScenario.payload);
                    await new Promise(resolve => setTimeout(resolve, 1000));
                }

                prevUEsRef.current = {};
                await startAllUEs();
                setIsRunning(true);

                // Wait for duration
                await new Promise(resolve => {
                    let remaining = duration;
                    const countdown = setInterval(() => {
                        remaining--;
                        setTimeRemaining(remaining);
                        if (remaining <= 0 || stopRetryRef.current) {
                            clearInterval(countdown);
                            resolve();
                        }
                    }, 1000);
                });

                await stopAllUEs();
                setIsRunning(false);

                if (i < numRetries && !stopRetryRef.current) {
                    await new Promise(resolve => setTimeout(resolve, 2000));
                }
            } catch (error) {
                console.error(`Error in retry ${i}:`, error);
            }
        }

        setIsRetrying(false);
        setCurrentRetry(0);
        setTotalRetries(0);

        // Reset UEs to start
        try {
            await stopAllUEs();
            if (activeScenario?.payload) {
                await importScenario(activeScenario.payload);
            }
        } catch (error) {
            console.error('Error resetting UE positions:', error);
        }
    }, [duration, activeScenario]);

    // Stop retries
    const stopRetries = useCallback(async () => {
        stopRetryRef.current = true;
        try {
            await stopAllUEs();
            setIsRunning(false);
            if (activeScenario?.payload) {
                await importScenario(activeScenario.payload);
            }
        } catch (error) {
            console.error('Error stopping retries:', error);
        }
    }, [activeScenario]);

    const value = {
        // State
        isRetrying,
        currentRetry,
        totalRetries,
        isRunning,
        timeRemaining,
        sessionId,
        mlMode,
        duration,
        scenarioName,
        activeScenario,
        handoverHistory,
        prevUEsRef,

        // Setters
        setMlMode,
        setDuration,
        setScenarioName,
        setActiveScenario,
        setIsRunning,
        setTimeRemaining,

        // Actions
        resetActiveScenario,
        startRetries,
        stopRetries,
        addHandover,
        clearAll,
    };

    return (
        <ExperimentContext.Provider value={value}>
            {children}
        </ExperimentContext.Provider>
    );
}

export function useExperiment() {
    const context = useContext(ExperimentContext);
    if (!context) {
        throw new Error('useExperiment must be used within an ExperimentProvider');
    }
    return context;
}
