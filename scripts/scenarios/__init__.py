"""
Enhanced Real-Life Scenarios for 5G Network Optimization.

This package contains realistic deployment scenarios for demonstrating
the ML-based handover optimization system in various real-world contexts.

Scenarios:
- smart_city_downtown: Dense urban deployment with mixed mobility
- highway_handover: High-speed vehicle handover demonstration
- stadium_event: Extreme density with QoS priority testing
- industrial_iot: mMTC devices in factory setting
- emergency_services: URLLC priority and preemption

Usage:
    from scripts.scenarios import SmartCityScenario
    scenario = SmartCityScenario()
    scenario.generate_topology()
    scenario.run_experiment(duration_minutes=10)
"""

from .base_scenario import BaseScenario

__all__ = ['BaseScenario']
