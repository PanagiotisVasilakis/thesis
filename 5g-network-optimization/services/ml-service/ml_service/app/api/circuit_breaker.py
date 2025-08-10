"""API endpoints for circuit breaker monitoring and management."""

from flask import Blueprint, jsonify, request
from typing import Dict, Any

from ..utils.circuit_breaker import circuit_registry
from ..utils.auth import require_auth

# Create blueprint for circuit breaker endpoints
circuit_breaker_bp = Blueprint('circuit_breaker', __name__, url_prefix='/api/v1/circuit-breakers')


@circuit_breaker_bp.route('/status', methods=['GET'])
@require_auth
def get_circuit_breaker_status() -> Dict[str, Any]:
    """Get status of all registered circuit breakers.
    
    Returns:
        Dictionary containing circuit breaker statistics
    """
    try:
        stats = circuit_registry.get_all_stats()
        open_circuits = circuit_registry.get_open_circuits()
        
        return jsonify({
            "status": "success",
            "data": {
                "circuit_breakers": stats,
                "open_circuits": list(open_circuits.keys()),
                "total_breakers": len(stats),
                "open_count": len(open_circuits),
                "health": "degraded" if open_circuits else "healthy"
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to get circuit breaker status: {str(e)}"
        }), 500


@circuit_breaker_bp.route('/reset', methods=['POST'])
@require_auth
def reset_circuit_breakers() -> Dict[str, Any]:
    """Reset all circuit breakers to closed state.
    
    Returns:
        Success message
    """
    try:
        circuit_registry.reset_all()
        
        return jsonify({
            "status": "success",
            "message": "All circuit breakers have been reset to closed state"
        }), 200
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to reset circuit breakers: {str(e)}"
        }), 500


@circuit_breaker_bp.route('/reset/<circuit_name>', methods=['POST'])
@require_auth
def reset_circuit_breaker(circuit_name: str) -> Dict[str, Any]:
    """Reset a specific circuit breaker to closed state.
    
    Args:
        circuit_name: Name of the circuit breaker to reset
        
    Returns:
        Success message or error
    """
    try:
        breaker = circuit_registry.get(circuit_name)
        if not breaker:
            return jsonify({
                "status": "error",
                "message": f"Circuit breaker '{circuit_name}' not found"
            }), 404
        
        breaker.reset()
        
        return jsonify({
            "status": "success",
            "message": f"Circuit breaker '{circuit_name}' has been reset to closed state"
        }), 200
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to reset circuit breaker '{circuit_name}': {str(e)}"
        }), 500


@circuit_breaker_bp.route('/health', methods=['GET'])
def health_check() -> Dict[str, Any]:
    """Health check endpoint for circuit breakers (no auth required).
    
    Returns basic health status for monitoring systems.
    
    Returns:
        Health status
    """
    try:
        open_circuits = circuit_registry.get_open_circuits()
        total_stats = circuit_registry.get_all_stats()
        
        # Determine overall health
        if not open_circuits:
            health_status = "healthy"
            http_status = 200
        elif len(open_circuits) < len(total_stats) / 2:
            health_status = "degraded"
            http_status = 200
        else:
            health_status = "unhealthy" 
            http_status = 503
        
        return jsonify({
            "status": health_status,
            "open_circuits": len(open_circuits),
            "total_circuits": len(total_stats),
            "timestamp": circuit_registry._get_current_timestamp() if hasattr(circuit_registry, '_get_current_timestamp') else None
        }), http_status
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Health check failed: {str(e)}"
        }), 500


@circuit_breaker_bp.route('/<circuit_name>/stats', methods=['GET'])
@require_auth
def get_circuit_breaker_stats(circuit_name: str) -> Dict[str, Any]:
    """Get detailed statistics for a specific circuit breaker.
    
    Args:
        circuit_name: Name of the circuit breaker
        
    Returns:
        Detailed circuit breaker statistics
    """
    try:
        breaker = circuit_registry.get(circuit_name)
        if not breaker:
            return jsonify({
                "status": "error",
                "message": f"Circuit breaker '{circuit_name}' not found"
            }), 404
        
        stats = breaker.get_stats()
        
        return jsonify({
            "status": "success",
            "data": stats
        }), 200
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to get stats for circuit breaker '{circuit_name}': {str(e)}"
        }), 500