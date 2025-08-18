"""Comprehensive integration tests for the ML pipeline."""

import pytest
import asyncio
import tempfile
import os
import json
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
import numpy as np

from ml_service.app.initialization.simplified_model_manager import SimplifiedModelManager
from ml_service.app.initialization.hot_swap_manager import HotSwapModelManager
from ml_service.app.models.lightgbm_selector import LightGBMSelector
from ml_service.app.models.lstm_selector import LSTMSelector
from ml_service.app.models.ensemble_selector import EnsembleSelector
from ml_service.app.clients.async_nef_client import AsyncNEFClient, AsyncNEFClientError
from ml_service.app.errors import ModelError, RequestValidationError
from ml_service.app.utils.synthetic_data import generate_synthetic_training_data


class TestMLPipelineIntegration:
    """Integration tests for the complete ML pipeline."""
    
    @pytest.fixture
    def temp_model_dir(self):
        """Create a temporary directory for model files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)
    
    @pytest.fixture
    def sample_training_data(self):
        """Generate sample training data for tests."""
        return generate_synthetic_training_data(50)
    
    @pytest.fixture
    def sample_features(self):
        """Sample feature dictionary for testing."""
        return {
            "latitude": 500.0,
            "longitude": 500.0,
            "speed": 2.5,
            "direction_x": 0.7,
            "direction_y": 0.7,
            "heading_change_rate": 0.1,
            "path_curvature": 0.05,
            "velocity": 2.5,
            "acceleration": 0.2,
            "cell_load": 0.3,
            "handover_count": 1,
            "time_since_handover": 5.0,
            "signal_trend": 0.1,
            "environment": 0.0,
            "rsrp_stddev": 2.5,
            "sinr_stddev": 1.2,
            "rsrp_current": -85.0,
            "sinr_current": 15.0,
            "rsrq_current": -8.0,
            "best_rsrp_diff": 5.0,
            "best_sinr_diff": 3.0,
            "best_rsrq_diff": 2.0,
            "altitude": 100.0,
            "rsrp_a1": -90.0,
            "sinr_a1": 12.0,
            "rsrq_a1": -10.0,
            "neighbor_cell_load_a1": 0.2,
            "rsrp_a2": -95.0,
            "sinr_a2": 8.0,
            "rsrq_a2": -12.0,
            "neighbor_cell_load_a2": 0.4,
        }

    def test_lightgbm_model_training_and_prediction(self, temp_model_dir, sample_training_data, sample_features):
        """Test complete LightGBM training and prediction pipeline."""
        model_path = temp_model_dir / "lightgbm_test.joblib"
        
        # Initialize and train model
        model = LightGBMSelector(str(model_path), neighbor_count=2)
        metrics = model.train(sample_training_data)
        
        # Verify training metrics
        assert metrics["samples"] == len(sample_training_data)
        assert metrics["classes"] > 0
        assert "feature_importance" in metrics
        assert "val_accuracy" in metrics
        
        # Test prediction
        result = model.predict(sample_features)
        assert "antenna_id" in result
        assert "confidence" in result
        assert isinstance(result["confidence"], float)
        assert 0.0 <= result["confidence"] <= 1.0
        
        # Test model persistence
        assert model.save()
        assert model_path.exists()
        
        # Test model loading
        new_model = LightGBMSelector(str(model_path), neighbor_count=2)
        assert new_model.load()
        
        # Verify loaded model produces same prediction
        loaded_result = new_model.predict(sample_features)
        assert loaded_result["antenna_id"] == result["antenna_id"]

    def test_lstm_model_training_and_prediction(self, temp_model_dir, sample_training_data, sample_features):
        """Test complete LSTM training and prediction pipeline."""
        model_path = temp_model_dir / "lstm_test"
        
        # Initialize and train model  
        model = LSTMSelector(str(model_path), neighbor_count=2, epochs=2)
        metrics = model.train(sample_training_data)
        
        # Verify training metrics
        assert metrics["samples"] == len(sample_training_data)
        assert metrics["classes"] > 0
        assert "history" in metrics
        
        # Test prediction
        result = model.predict(sample_features)
        assert "antenna_id" in result
        assert "confidence" in result
        assert isinstance(result["confidence"], float)
        assert 0.0 <= result["confidence"] <= 1.0
        
        # Test model persistence
        assert model.save()
        assert Path(model_path).exists()
        
        # Test model loading
        new_model = LSTMSelector(str(model_path), neighbor_count=2)
        assert new_model.load()
        
        # Verify loaded model can make predictions
        loaded_result = new_model.predict(sample_features)
        assert "antenna_id" in loaded_result
        assert "confidence" in loaded_result

    def test_ensemble_model_integration(self, sample_training_data, sample_features):
        """Test ensemble model combining multiple selectors."""
        # Create individual models
        lgb_model = LightGBMSelector(neighbor_count=2)
        lstm_model = LSTMSelector(neighbor_count=2, epochs=2)
        
        # Train individual models
        lgb_model.train(sample_training_data)
        lstm_model.train(sample_training_data)
        
        # Create and test ensemble
        ensemble = EnsembleSelector([lgb_model, lstm_model], neighbor_count=2)
        
        # Test ensemble training
        ensemble_metrics = ensemble.train(sample_training_data)
        assert "LightGBMSelector" in ensemble_metrics
        assert "LSTMSelector" in ensemble_metrics
        
        # Test ensemble prediction
        result = ensemble.predict(sample_features)
        assert "antenna_id" in result
        assert "confidence" in result
        assert isinstance(result["confidence"], float)
        assert 0.0 <= result["confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_simplified_model_manager(self, temp_model_dir, sample_training_data, sample_features):
        """Test the simplified model manager functionality."""
        model_path = temp_model_dir / "manager_test.joblib"
        
        # Initialize manager
        manager = SimplifiedModelManager()
        
        # Test async initialization
        success = await manager.initialize_async(str(model_path), model_type="lightgbm", neighbor_count=2)
        assert success
        assert manager.is_ready()
        
        # Test getting model
        model = manager.get_model()
        assert model is not None
        
        # Test prediction through manager
        result = model.predict(sample_features)
        assert "antenna_id" in result
        assert "confidence" in result
        
        # Test feedback mechanism
        feedback_sample = {
            **sample_features,
            "optimal_antenna": result["antenna_id"]
        }
        retrained = manager.feed_feedback(feedback_sample, success=True)
        # Retrained might be False if no drift detected
        assert isinstance(retrained, bool)
        
        # Test model saving
        assert manager.save_model()
        assert model_path.exists()
        
        # Clean up
        manager.shutdown()

    @pytest.mark.asyncio 
    async def test_hot_swap_manager(self, temp_model_dir, sample_training_data, sample_features):
        """Test hot-swap model manager for zero-downtime updates."""
        model_path1 = temp_model_dir / "model_v1.joblib"
        model_path2 = temp_model_dir / "model_v2.joblib"
        
        # Train and save two different models
        model1 = LightGBMSelector(str(model_path1), neighbor_count=2, n_estimators=50)
        model1.train(sample_training_data[:25])  # Train on first half
        model1.save()
        
        model2 = LightGBMSelector(str(model_path2), neighbor_count=2, n_estimators=100)  
        model2.train(sample_training_data[25:])  # Train on second half
        model2.save()
        
        # Initialize hot-swap manager
        manager = HotSwapModelManager(str(temp_model_dir))
        
        # Initialize with first model
        success = await manager.initialize(str(model_path1), model_type="lightgbm", neighbor_count=2)
        assert success
        assert manager.is_ready()
        
        # Test initial prediction
        initial_model = manager.get_model()
        initial_result = initial_model.predict(sample_features)
        
        # Perform hot swap to second model
        swap_success = await manager.hot_swap_model(str(model_path2), validate=True)
        assert swap_success
        
        # Verify new model is active
        new_model = manager.get_model()
        new_result = new_model.predict(sample_features)
        
        # Results might be different due to different training data
        assert "antenna_id" in new_result
        assert "confidence" in new_result
        
        # Test health callback functionality
        def mock_health_check(model):
            return hasattr(model, 'model') and model.model is not None
        
        manager.register_health_callback("basic_health", mock_health_check)
        
        # Test another swap with health check
        swap_success2 = await manager.hot_swap_model(str(model_path1), validate=True)
        assert swap_success2
        
        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_async_nef_client_integration(self):
        """Test async NEF client with mock server responses."""
        client = AsyncNEFClient("http://mock-nef:8080", username="user", password="pass", timeout=5.0)

        # Mock internal request method to avoid real HTTP calls
        with patch.object(client, '_make_request_with_retry', new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = [
                {"access_token": "test_token"},  # login
                {"status_code": 200},             # get_status
                {"ue_id": "test_ue", "features": {}},  # get_feature_vector
                {"ue_id": "ue1", "features": {}},      # batch get_feature_vector first
                {"ue_id": "ue2", "features": {}},      # batch get_feature_vector second
                {"status_code": 200},             # health_check -> get_status
            ]

            # Test login
            login_success = await client.login()
            assert login_success
            assert client.token == "test_token"

            # Test status check
            status = await client.get_status()
            assert status["status_code"] == 200

            # Test feature vector retrieval
            features = await client.get_feature_vector("test_ue")
            assert "ue_id" in features

            # Test batch feature vector retrieval
            batch_features = await client.batch_get_feature_vectors(["ue1", "ue2"])
            assert len(batch_features) == 2

            # Test health check
            health = await client.health_check()
            assert health is True

        # Ensure the client's close method is properly awaited
        with patch.object(client, 'close', new_callable=AsyncMock, wraps=client.close) as mock_close:
            await client.close()
            mock_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_error_handling_integration(self, temp_model_dir):
        """Test error handling across the ML pipeline."""
        
        # Test invalid model path
        manager = SimplifiedModelManager()
        success = await manager.initialize_async("/nonexistent/path.joblib")
        assert not success  # Should fail gracefully
        
        # Test invalid training data
        model = LightGBMSelector(neighbor_count=2)
        with pytest.raises(ValueError):
            model.train([])  # Empty training data should raise error
        
        # Test prediction with missing features
        model = LightGBMSelector(neighbor_count=2)
        model.train(generate_synthetic_training_data(10))
        
        # Test with BaseModelMixin's validate_features
        with pytest.raises(ValueError, match="Missing required features"):
            model.validate_features({"latitude": 100})  # Missing most features

        # Test range validation
        sample = generate_synthetic_training_data(1)[0]
        feats = model.extract_features(sample)
        feats["speed"] = 200.0  # beyond configured max
        with pytest.raises(ValueError, match="speed"):
            model.validate_features(feats)
        
        # Test fallback prediction mechanism
        incomplete_features = {"latitude": 100, "longitude": 200}
        result = model.get_prediction_with_fallback(
            incomplete_features, 
            "fallback_antenna", 
            0.1
        )
        assert result["antenna_id"] == "fallback_antenna"
        assert result["confidence"] == 0.1

    @pytest.mark.asyncio
    async def test_async_nef_client_error_handling(self):
        """Test async NEF client error handling."""
        client = AsyncNEFClient("http://unreachable:8080", username="user", password="pass", timeout=1.0, max_retries=2)

        # Test connection failure returns False without raising
        with patch.object(client, '_make_request_with_retry', side_effect=AsyncNEFClientError("connection")):
            assert not await client.login()

        # Test server error handling returns error dict
        with patch.object(client, '_make_request_with_retry', side_effect=AsyncNEFClientError("server error")):
            status = await client.get_status()
            assert status["status_code"] == 0
            assert "server error" in status["error"]

        await client.close()

    def test_model_validation_integration(self, sample_features):
        """Test input validation integration across models."""
        from ml_service.app.validation import validate_json_input, LoginRequest
        from ml_service.app.schemas import PredictionRequest
        
        # Test schema validation
        valid_login = {"username": "test", "password": "test123"}
        login_req = LoginRequest.parse_obj(valid_login)
        assert login_req.username == "test"
        
        # Test prediction request validation
        prediction_data = {
            "ue_id": "test_ue",
            "latitude": 500.0,
            "longitude": 500.0,
            "speed": 2.5,
            "rf_metrics": {
                "antenna_1": {"rsrp": -85, "sinr": 15, "rsrq": -8}
            }
        }
        
        pred_req = PredictionRequest.parse_obj(prediction_data)
        assert pred_req.ue_id == "test_ue"
        assert pred_req.latitude == 500.0

    def test_end_to_end_pipeline(self, temp_model_dir, sample_training_data, sample_features):
        """Test complete end-to-end ML pipeline."""
        model_path = temp_model_dir / "e2e_test.joblib"
        
        # 1. Initialize model
        model = LightGBMSelector(str(model_path), neighbor_count=2)
        
        # 2. Train model
        training_metrics = model.train(sample_training_data)
        assert training_metrics["samples"] > 0
        
        # 3. Save model
        save_success = model.save()
        assert save_success
        
        # 4. Load model in new instance
        loaded_model = LightGBMSelector(str(model_path), neighbor_count=2)
        load_success = loaded_model.load()
        assert load_success
        
        # 5. Make prediction
        prediction = loaded_model.predict(sample_features)
        assert "antenna_id" in prediction
        assert "confidence" in prediction
        
        # 6. Simulate feedback loop
        feedback_sample = {
            **sample_features,
            "optimal_antenna": prediction["antenna_id"]
        }
        
        # 7. Use BaseModelMixin functionality
        features_array, labels_array = loaded_model.build_dataset([feedback_sample])
        assert len(features_array) == 1
        assert len(labels_array) == 1
        
        # 8. Test feature validation
        loaded_model.validate_features(sample_features)  # Should not raise
        
        # 9. Test prediction with fallback
        result_with_fallback = loaded_model.get_prediction_with_fallback(
            sample_features, "default_antenna", 0.5
        )
        assert result_with_fallback["antenna_id"] is not None