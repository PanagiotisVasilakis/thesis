"""Test the LightGBMSelector model."""
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
from ml_service.app.models.lightgbm_selector import LightGBMSelector
from ml_service.app.utils.synthetic_data import generate_synthetic_training_data

def test_model_training_and_prediction(tmp_path):
    """Training the model should yield predictions with reasonable accuracy."""

    data = generate_synthetic_training_data(1000)

    train_data, test_data = train_test_split(data, test_size=0.2, random_state=42)

    model = LightGBMSelector()
    metrics = model.train(train_data)

    correct = 0
    for sample in test_data:
        features = model.extract_features(sample)
        prediction = model.predict(features)

        if prediction['antenna_id'] == sample['optimal_antenna']:
            correct += 1

    accuracy = correct / len(test_data)
    
    # Visualize feature importance
    feature_importance = metrics.get('feature_importance', {})
    if feature_importance:
        features = list(feature_importance.keys())
        importance = list(feature_importance.values())

        plt.figure(figsize=(10, 6))
        plt.barh(features, importance)
        plt.xlabel('Importance')
        plt.title('Feature Importance')
        plt.tight_layout()

        out_path = tmp_path / "feature_importance.png"
        plt.savefig(out_path)
        assert out_path.exists()
        out_path.unlink()

    assert accuracy > 0.7, f"Model accuracy too low: {accuracy:.2%}"

