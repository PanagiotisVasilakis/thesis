# Feature Transformation Registry Documentation

The Feature Transformation Registry provides a flexible, extensible system for dynamically registering and managing feature transformations in the 5G ML service.

## Overview

The transformation registry allows you to:
- Register custom feature transformations dynamically
- Organize transformations by category and priority
- Create complex feature extraction pipelines
- Enable/disable transformations at runtime
- Cache transformation results for performance
- Monitor transformation execution statistics

## Architecture

### Core Components

1. **TransformationRegistry**: Central registry for managing transformations
2. **FeatureTransformation**: Abstract base class for transformations
3. **TransformationMetadata**: Metadata describing transformations
4. **FeatureExtractionPipeline**: Unified pipeline for executing transformations

### Transformation Categories

- **SPATIAL**: Geographic/position transformations
- **TEMPORAL**: Time-based transformations  
- **SIGNAL**: RF signal processing
- **MOBILITY**: Movement and velocity transformations
- **NETWORK**: Network topology transformations
- **STATISTICAL**: Statistical aggregations
- **CUSTOM**: User-defined transformations

### Priority Levels

1. **CRITICAL**: Must execute first (e.g., data validation)
2. **HIGH**: High priority (e.g., core features)
3. **NORMAL**: Normal priority (default)
4. **LOW**: Low priority (e.g., derived features)
5. **OPTIONAL**: Optional (e.g., experimental features)

## Quick Start

### Basic Usage

```python
from ml_service.app.features.transformation_registry import get_transformation_registry
from ml_service.app.features.unified_pipeline import get_feature_pipeline

# Get the global registry and pipeline
registry = get_transformation_registry()
pipeline = get_feature_pipeline()

# Extract features from UE data
ue_data = {
    "latitude": 37.7749,
    "longitude": -122.4194,
    "speed": 15.0,
    "rsrp_current": -85,
    "sinr_current": 12,
    "timestamp": "2024-01-01T12:00:00Z"
}

# Extract all features
features = pipeline.extract_features(ue_data)
print(f"Extracted {len(features)} features")
```

### Registering Custom Transformations

#### Method 1: Using the Decorator

```python
from ml_service.app.features.transformation_registry import register_transformation

@register_transformation(
    name="my_custom_transform",
    category="custom",
    priority=3,
    description="My custom feature transformation",
    input_features=["latitude", "longitude"],
    output_features=["custom_feature_1", "custom_feature_2"]
)
def my_custom_transform(features, context=None):
    lat = features.get("latitude", 0)
    lon = features.get("longitude", 0)
    
    # Your custom logic here
    custom_feature_1 = lat * lon
    custom_feature_2 = abs(lat - lon)
    
    return {
        "custom_feature_1": custom_feature_1,
        "custom_feature_2": custom_feature_2
    }
```

#### Method 2: Manual Registration

```python
from ml_service.app.features.transformation_registry import (
    get_transformation_registry,
    TransformationMetadata,
    TransformationCategory,
    TransformationPriority
)

def distance_calculation(features, context=None):
    """Calculate distance between two points."""
    lat1 = features.get("lat1", 0)
    lon1 = features.get("lon1", 0) 
    lat2 = features.get("lat2", 0)
    lon2 = features.get("lon2", 0)
    
    # Haversine formula
    import math
    R = 6371  # Earth's radius in km
    
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    
    a = (math.sin(dlat/2)**2 + 
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * 
         math.sin(dlon/2)**2)
    
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    distance = R * c
    
    return {"distance_km": distance}

# Create metadata
metadata = TransformationMetadata(
    name="distance_calculation",
    description="Calculate distance between two geographic points",
    category=TransformationCategory.SPATIAL,
    priority=TransformationPriority.NORMAL,
    input_features=["lat1", "lon1", "lat2", "lon2"],
    output_features=["distance_km"],
    version="1.0.0",
    author="your_name"
)

# Register transformation
registry = get_transformation_registry()
registry.register_transformation("distance_calculation", distance_calculation, metadata)
```

## Advanced Examples

### Complex Signal Processing Transformation

```python
import numpy as np
from scipy import signal
from ml_service.app.features.transformation_registry import register_transformation

@register_transformation(
    name="advanced_signal_processing",
    category="signal",
    priority=2,
    description="Advanced signal processing with filtering and analysis",
    input_features=["rsrp_history", "sinr_history"],
    output_features=["signal_trend", "signal_stability", "dominant_frequency"]
)
def advanced_signal_processing(features, context=None):
    """Advanced signal processing transformation."""
    rsrp_history = features.get("rsrp_history", [])
    sinr_history = features.get("sinr_history", [])
    
    if len(rsrp_history) < 10 or len(sinr_history) < 10:
        return {
            "signal_trend": 0,
            "signal_stability": 0,
            "dominant_frequency": 0
        }
    
    # Convert to numpy arrays
    rsrp_array = np.array(rsrp_history[-50:])  # Last 50 samples
    sinr_array = np.array(sinr_history[-50:])
    
    # Calculate trend using linear regression
    x = np.arange(len(rsrp_array))
    rsrp_trend = np.polyfit(x, rsrp_array, 1)[0]
    sinr_trend = np.polyfit(x, sinr_array, 1)[0]
    signal_trend = (rsrp_trend + sinr_trend) / 2
    
    # Calculate stability (inverse of standard deviation)
    rsrp_stability = 1 / (1 + np.std(rsrp_array))
    sinr_stability = 1 / (1 + np.std(sinr_array))
    signal_stability = (rsrp_stability + sinr_stability) / 2
    
    # Find dominant frequency using FFT
    combined_signal = rsrp_array + sinr_array
    fft = np.fft.fft(combined_signal)
    freqs = np.fft.fftfreq(len(combined_signal))
    dominant_freq_idx = np.argmax(np.abs(fft[1:len(fft)//2])) + 1
    dominant_frequency = abs(freqs[dominant_freq_idx])
    
    return {
        "signal_trend": float(signal_trend),
        "signal_stability": float(signal_stability), 
        "dominant_frequency": float(dominant_frequency)
    }
```

### Machine Learning-Based Transformation

```python
import joblib
from sklearn.preprocessing import StandardScaler
from ml_service.app.features.transformation_registry import register_transformation

# Assume you have a pre-trained model
try:
    mobility_classifier = joblib.load('/path/to/mobility_classifier.pkl')
    mobility_scaler = joblib.load('/path/to/mobility_scaler.pkl')
    
    @register_transformation(
        name="ml_mobility_prediction",
        category="mobility",
        priority=3,
        description="ML-based mobility pattern prediction",
        input_features=["speed", "acceleration", "heading_change_rate"],
        output_features=["predicted_mobility_class", "mobility_confidence"]
    )
    def ml_mobility_prediction(features, context=None):
        """Use ML model to predict mobility patterns."""
        speed = features.get("speed", 0)
        acceleration = features.get("acceleration", 0)
        heading_change = features.get("heading_change_rate", 0)
        
        # Prepare features for model
        feature_vector = np.array([[speed, acceleration, heading_change]])
        scaled_features = mobility_scaler.transform(feature_vector)
        
        # Predict
        prediction = mobility_classifier.predict(scaled_features)[0]
        probabilities = mobility_classifier.predict_proba(scaled_features)[0]
        confidence = max(probabilities)
        
        return {
            "predicted_mobility_class": prediction,
            "mobility_confidence": confidence
        }
        
except FileNotFoundError:
    print("Mobility classifier model not found, skipping ML transformation")
```

### Class-Based Transformation

```python
from ml_service.app.features.transformation_registry import (
    FeatureTransformation,
    TransformationMetadata,
    TransformationCategory,
    TransformationPriority,
    get_transformation_registry
)

class NetworkTopologyAnalyzer(FeatureTransformation):
    """Advanced network topology analysis transformation."""
    
    def __init__(self):
        metadata = TransformationMetadata(
            name="network_topology_analysis",
            description="Comprehensive network topology analysis",
            category=TransformationCategory.NETWORK,
            priority=TransformationPriority.HIGH,
            input_features=["neighbor_cells", "signal_strengths", "cell_loads"],
            output_features=["topology_complexity", "load_balance_score", "coverage_quality"]
        )
        super().__init__(metadata)
        
        # Initialize any required state
        self.topology_cache = {}
    
    def transform(self, features, context=None):
        """Perform network topology analysis."""
        neighbor_cells = features.get("neighbor_cells", [])
        signal_strengths = features.get("signal_strengths", {})
        cell_loads = features.get("cell_loads", {})
        
        # Topology complexity based on number of neighbors and signal variation
        topology_complexity = len(neighbor_cells) * np.std(list(signal_strengths.values()))
        
        # Load balance score
        if cell_loads:
            load_values = list(cell_loads.values())
            load_balance_score = 1 - (np.std(load_values) / np.mean(load_values))
        else:
            load_balance_score = 0
        
        # Coverage quality based on signal strength distribution
        if signal_strengths:
            signal_values = list(signal_strengths.values())
            coverage_quality = np.mean(signal_values) / 100  # Normalize
        else:
            coverage_quality = 0
        
        return {
            "topology_complexity": topology_complexity,
            "load_balance_score": load_balance_score,
            "coverage_quality": coverage_quality
        }

# Register the class-based transformation
registry = get_transformation_registry()
analyzer = NetworkTopologyAnalyzer()
registry.register_transformation("network_topology_analysis", analyzer)
```

## Pipeline Configuration

### Configuring Pipeline Execution

```python
from ml_service.app.features.unified_pipeline import get_feature_pipeline

pipeline = get_feature_pipeline()

# Configure which transformations to run
pipeline.configure_pipeline(
    enabled_transformations=[
        "normalize_coordinates",
        "signal_quality_score",
        "mobility_classification",
        "my_custom_transform"
    ],
    category_filter=["spatial", "signal", "custom"],
    priority_filter=[1, 2, 3]  # Only run high-priority transformations
)

# Set custom execution order
pipeline.configure_pipeline(
    execution_order=[
        "normalize_coordinates",      # Run first
        "signal_quality_score",       # Then signal processing
        "mobility_classification",    # Then mobility
        "my_custom_transform"         # Finally custom
    ]
)
```

### Batch Processing

```python
# Process multiple UEs at once
ue_data_batch = [
    {"latitude": 37.7749, "longitude": -122.4194, "speed": 15.0},
    {"latitude": 37.7849, "longitude": -122.4094, "speed": 25.0},
    {"latitude": 37.7949, "longitude": -122.3994, "speed": 35.0}
]

# Extract features for all UEs (parallel processing)
feature_batch = pipeline.extract_features_batch(
    ue_data_batch,
    parallel=True
)

print(f"Processed {len(feature_batch)} UE feature sets")
```

### Async Processing

```python
import asyncio

async def process_ue_async():
    ue_data = {
        "latitude": 37.7749,
        "longitude": -122.4194,
        "speed": 15.0,
        "rsrp_current": -85
    }
    
    # Async feature extraction
    features = await pipeline.extract_features_async(ue_data)
    return features

# Run async processing
features = asyncio.run(process_ue_async())
```

## Monitoring and Statistics

### Getting Pipeline Statistics

```python
# Get comprehensive statistics
stats = pipeline.get_pipeline_statistics()
print(f"Total executions: {stats['execution_statistics']['total_executions']}")
print(f"Average execution time: {stats['average_execution_time']:.4f}s")
print(f"Cache hit rate: {stats['cache_hit_rate']:.2%}")

# Get registry statistics  
registry_stats = registry.get_registry_statistics()
print(f"Total transformations: {registry_stats['total_transformations']}")
print(f"Category distribution: {registry_stats['category_counts']}")
```

### Monitoring Individual Transformations

```python
# Get statistics for specific transformation
transform_stats = registry.get_transformation_metadata("signal_quality_score")
print(f"Transformation: {transform_stats['name']}")
print(f"Category: {transform_stats['category']}")
print(f"Description: {transform_stats['description']}")

# Get execution statistics
all_stats = registry.get_registry_statistics()
for name, stats in all_stats['transformation_statistics'].items():
    print(f"{name}: {stats['execution_count']} executions, "
          f"avg time: {stats['average_execution_time']:.4f}s")
```

## Best Practices

### 1. Transformation Design

- **Single Responsibility**: Each transformation should have one clear purpose
- **Input Validation**: Always validate required inputs
- **Error Handling**: Handle missing or invalid data gracefully
- **Performance**: Optimize for repeated execution
- **Documentation**: Provide clear descriptions and examples

```python
@register_transformation(
    name="robust_example",
    category="custom",
    description="Example of a robust transformation",
    input_features=["required_field"],
    output_features=["output_field"]
)
def robust_example(features, context=None):
    """Example of robust transformation design."""
    # Input validation
    required_field = features.get("required_field")
    if required_field is None:
        logger.warning("Missing required_field, using default")
        return {"output_field": 0}
    
    # Type checking
    if not isinstance(required_field, (int, float)):
        logger.warning(f"Invalid type for required_field: {type(required_field)}")
        return {"output_field": 0}
    
    # Range validation
    if required_field < 0 or required_field > 100:
        logger.warning(f"required_field out of range: {required_field}")
        required_field = max(0, min(100, required_field))
    
    # Computation with error handling
    try:
        result = complex_computation(required_field)
        return {"output_field": result}
    except Exception as exc:
        logger.error(f"Computation failed: {exc}")
        return {"output_field": 0}
```

### 2. Performance Optimization

- **Caching**: Use caching for expensive computations
- **Vectorization**: Use NumPy for numerical operations
- **Early Return**: Return early for invalid inputs
- **Memory Management**: Clean up large temporary objects

```python
import functools
import numpy as np

@functools.lru_cache(maxsize=1000)
def expensive_lookup(key):
    """Cached expensive lookup operation."""
    # Simulate expensive operation
    return complex_calculation(key)

@register_transformation(
    name="optimized_example",
    category="custom",
    description="Example of performance-optimized transformation"
)
def optimized_example(features, context=None):
    """Performance-optimized transformation."""
    # Use vectorized operations
    values = np.array([features.get(f"value_{i}", 0) for i in range(10)])
    processed_values = np.sqrt(values + 1)  # Vectorized operation
    
    # Use caching for expensive lookups
    lookup_key = features.get("lookup_key", "default")
    cached_result = expensive_lookup(lookup_key)
    
    # Early return for edge cases
    if np.all(processed_values == 0):
        return {"result": 0}
    
    result = np.mean(processed_values) + cached_result
    return {"result": float(result)}
```

### 3. Testing Transformations

```python
import unittest
from ml_service.app.features.transformation_registry import get_transformation_registry

class TestCustomTransformations(unittest.TestCase):
    
    def setUp(self):
        self.registry = get_transformation_registry()
    
    def test_my_custom_transform(self):
        """Test custom transformation."""
        # Get transformation
        transform = self.registry.get_transformation("my_custom_transform")
        self.assertIsNotNone(transform)
        
        # Test with valid input
        features = {"latitude": 10.0, "longitude": 20.0}
        result = transform.execute(features)
        
        self.assertIn("custom_feature_1", result)
        self.assertIn("custom_feature_2", result)
        self.assertEqual(result["custom_feature_1"], 200.0)
        self.assertEqual(result["custom_feature_2"], 10.0)
        
        # Test with missing input
        incomplete_features = {"latitude": 10.0}
        result = transform.execute(incomplete_features)
        self.assertEqual(result, {})  # Should return empty due to validation
    
    def test_pipeline_integration(self):
        """Test transformation in pipeline."""
        from ml_service.app.features.unified_pipeline import get_feature_pipeline
        
        pipeline = get_feature_pipeline()
        
        # Configure to use only our transformation
        pipeline.configure_pipeline(
            enabled_transformations=["my_custom_transform"]
        )
        
        features = {"latitude": 5.0, "longitude": 10.0}
        result = pipeline.extract_features(features)
        
        # Should include both input and output features
        self.assertIn("latitude", result)
        self.assertIn("longitude", result)
        self.assertIn("custom_feature_1", result)
        self.assertIn("custom_feature_2", result)

if __name__ == "__main__":
    unittest.main()
```

## Troubleshooting

### Common Issues

1. **Transformation Not Executing**
   - Check if transformation is enabled in pipeline configuration
   - Verify input features are available
   - Check transformation dependencies

2. **Performance Issues**
   - Enable caching for repeated operations
   - Use vectorized operations for numerical data
   - Consider parallel processing for batch operations

3. **Memory Issues**
   - Clear cache periodically: `pipeline.clear_cache()`
   - Optimize transformation algorithms
   - Use generators for large datasets

4. **Validation Failures**
   - Check input feature types and ranges
   - Verify transformation metadata is correct
   - Add logging to identify specific issues

### Debugging

```python
import logging

# Enable debug logging
logging.getLogger('ml_service.app.features').setLevel(logging.DEBUG)

# Add debug information to transformations
@register_transformation(name="debug_example", category="custom")
def debug_example(features, context=None):
    logger = logging.getLogger(__name__)
    logger.debug(f"Input features: {list(features.keys())}")
    
    result = {"debug_output": len(features)}
    logger.debug(f"Output: {result}")
    
    return result
```

This documentation provides comprehensive guidance for using and extending the feature transformation registry system. The registry enables flexible, maintainable, and scalable feature engineering for the 5G ML service.