# Save this as tests/test_ml_components.py

import numpy as np
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
import logging
from ml_service.app.models.lightgbm_selector import LightGBMSelector
from ml_service.app.utils.synthetic_data import (
    generate_synthetic_training_data,
    _generate_antenna_positions,
)

logger = logging.getLogger(__name__)

NUM_ANTENNAS = 4


def test_feature_extraction():
    """Feature extraction should produce expected keys."""

    model = LightGBMSelector()

    ue_data = {
        'ue_id': 'test_ue_1',
        'latitude': 500.0,
        'longitude': 250.0,
        'altitude': 0.0,
        'speed': 5.0,
        'direction': [0.8, 0.6, 0],
        'connected_to': 'antenna_1',
        'rf_metrics': {
            'antenna_1': {'rsrp': -85, 'sinr': 10},
            'antenna_2': {'rsrp': -95, 'sinr': 5},
            'antenna_3': {'rsrp': -105, 'sinr': 2}
        },
    }

    features = model.extract_features(ue_data)

    expected_features = [
        'latitude', 'longitude', 'altitude', 'speed',
        'direction_x', 'direction_y',
        'rsrp_current', 'sinr_current',
        'best_rsrp_diff', 'best_sinr_diff',
        'rsrp_a1', 'sinr_a1', 'rsrp_a2', 'sinr_a2'
    ]

    for feature in expected_features:
        assert feature in features, f"Missing expected feature: {feature}"

def test_model_training_and_prediction(tmp_path):
    """Training on synthetic data should achieve reasonable accuracy."""

    data = generate_synthetic_training_data(100, num_antennas=NUM_ANTENNAS)

    train_data, test_data = train_test_split(data, test_size=0.2, random_state=42)

    model = LightGBMSelector()
    metrics = model.train(train_data)

    correct = 0
    predictions = []

    for sample in test_data:
        features = model.extract_features(sample)
        prediction = model.predict(features)

        predictions.append(
            (
                sample['ue_id'],
                sample['latitude'],
                sample['longitude'],
                sample['optimal_antenna'],
                prediction['antenna_id'],
                prediction['confidence'],
            )
        )

        if prediction['antenna_id'] == sample['optimal_antenna']:
            correct += 1

    accuracy = correct / len(test_data)
    logger.info(f"Accuracy: {accuracy:.2%}")
    
    # Visualize feature importance if available
    feature_importance = metrics.get('feature_importance', {})
    if feature_importance:
        logger.info("\nFeature importance:")
        sorted_features = sorted(
            feature_importance.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        for feature, importance in sorted_features:
            logger.info(f"  {feature}: {importance:.4f}")
        
        # Plot feature importance
        plt.figure(figsize=(10, 6))
        features = [f[0] for f in sorted_features]
        importances = [f[1] for f in sorted_features]
        
        plt.barh(features, importances)
        plt.xlabel('Importance')
        plt.title('Feature Importance')
        plt.tight_layout()
        
        out_path = tmp_path / "feature_importance.png"
        plt.savefig(out_path)
        plt.close()
        assert out_path.exists()
        out_path.unlink()

        logger.info(f"Feature importance visualization saved to {out_path}")
    
    # Visualize predictions in a 2D space
    visualize_predictions(test_data, predictions, tmp_path, NUM_ANTENNAS)
    
    # Save model
    try:
        model.save('output/test_model.joblib')
    except Exception as e:  # pragma: no cover - save failures should surface
        import pytest

        pytest.fail(f"Failed to save model: {e}")

    assert accuracy > 0.7, f"Model accuracy too low: {accuracy:.2%}"

def visualize_predictions(test_data, predictions, tmp_path, num_antennas: int):
    """Visualize predictions in a 2D space for an arbitrary antenna count."""
    logger.info("\nVisualizing predictions...")

    lats = [sample['latitude'] for sample in test_data]
    lons = [sample['longitude'] for sample in test_data]
    true_antennas = [sample['optimal_antenna'] for sample in test_data]
    pred_antennas = [pred[4] for pred in predictions]

    unique_antennas = sorted({a for a in true_antennas} | {p for p in pred_antennas})

    colors = plt.cm.tab10.colors
    antenna_colors = {a: colors[i % len(colors)] for i, a in enumerate(unique_antennas)}

    plt.figure(figsize=(12, 10))

    antennas = _generate_antenna_positions(num_antennas)
    for antenna_id, pos in antennas.items():
        plt.plot(pos[0], pos[1], 'ko', markersize=12)
        plt.text(pos[0] + 20, pos[1] + 20, antenna_id, fontsize=12)

    for lat, lon, true_ant, pred_ant in zip(lats, lons, true_antennas, pred_antennas):
        marker = 'o' if true_ant == pred_ant else 'x'
        plt.plot(lat, lon, marker, color=antenna_colors[pred_ant], alpha=0.6, markersize=6)

    grid_resolution = 50
    x_grid = np.linspace(0, 1000, grid_resolution)
    y_grid = np.linspace(0, 866, grid_resolution)
    X, Y = np.meshgrid(x_grid, y_grid)

    boundary_model = LightGBMSelector()
    boundary_model.train(test_data)

    Z = np.empty((grid_resolution, grid_resolution), dtype=object)
    dummy_rf = {aid: {'rsrp': -80, 'sinr': 10} for aid in unique_antennas}

    for i in range(grid_resolution):
        for j in range(grid_resolution):
            dummy_data = {
                'latitude': X[i, j],
                'longitude': Y[i, j],
                'speed': 1.0,
                'direction': [1, 0, 0],
                'connected_to': unique_antennas[0],
                'rf_metrics': dummy_rf,
            }

            features = boundary_model.extract_features(dummy_data)
            prediction = boundary_model.predict(features)
            Z[i, j] = prediction['antenna_id']

    antenna_map = {aid: idx + 1 for idx, aid in enumerate(unique_antennas)}
    Z_numeric = np.vectorize(lambda a: antenna_map.get(a, 0))(Z)

    plt.contourf(X, Y, Z_numeric, levels=len(unique_antennas), alpha=0.2, cmap='viridis')

    plt.grid(True)
    plt.xlabel('X Position (m)')
    plt.ylabel('Y Position (m)')
    plt.title('Antenna Selection Predictions')

    handles = [
        plt.Line2D([0], [0], marker='o', color='w', markerfacecolor=color, markersize=10, label=aid)
        for aid, color in antenna_colors.items()
    ]
    handles.append(plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='k', markersize=10, label='Antenna Location'))
    handles.append(plt.Line2D([0], [0], marker='o', color='k', markerfacecolor='w', markersize=10, label='Correct Prediction'))
    handles.append(plt.Line2D([0], [0], marker='x', color='k', markerfacecolor='w', markersize=10, label='Incorrect Prediction'))

    plt.legend(handles=handles)

    out_path = tmp_path / "prediction_visualization.png"
    plt.savefig(out_path)
    plt.close()
    assert out_path.exists()
    out_path.unlink()

    logger.info(f"Prediction visualization saved to {out_path}")
