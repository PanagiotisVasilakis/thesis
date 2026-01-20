import { createContext, useContext, useState, useRef, useCallback } from 'react';
import { startAllUEs, stopAllUEs, getUEs, importScenario } from '../api/nefClient';

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
    const [duration, setDuration] = useState(60);
    const [scenarioName, setScenarioName] = useState('');

    const stopRetryRef = useRef(false);
    const prevUEsRef = useRef({});

    // Handover history (persisted to localStorage)
    const [handoverHistory, setHandoverHistory] = useState(() => {
        const saved = localStorage.getItem('handover_history');
        return saved ? JSON.parse(saved) : [];
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
                // Reset UEs to initial positions
                if (scenarioName) {
                    await importScenario({ name: scenarioName });
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
            if (scenarioName) {
                await importScenario({ name: scenarioName });
            }
        } catch (error) {
            console.error('Error resetting UE positions:', error);
        }
    }, [duration, scenarioName]);

    // Stop retries
    const stopRetries = useCallback(async () => {
        stopRetryRef.current = true;
        try {
            await stopAllUEs();
            setIsRunning(false);
            if (scenarioName) {
                await importScenario({ name: scenarioName });
            }
        } catch (error) {
            console.error('Error stopping retries:', error);
        }
    }, [scenarioName]);

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
        handoverHistory,
        prevUEsRef,

        // Setters
        setMlMode,
        setDuration,
        setScenarioName,
        setIsRunning,
        setTimeRemaining,

        // Actions
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
