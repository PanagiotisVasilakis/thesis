"""Tests for metrics authentication functionality."""

import pytest
import base64
import time
import jwt
from flask import Flask
from unittest.mock import patch, MagicMock

from ml_service.app.auth.metrics_auth import (
    MetricsAuthenticator,
    MetricsAuthError,
    require_metrics_auth,
    get_metrics_authenticator,
    create_metrics_auth_token,
    validate_metrics_request
)


class TestMetricsAuthenticator:
    """Test cases for MetricsAuthenticator class."""
    
    def test_basic_auth_validation_success(self):
        """Test successful basic authentication."""
        auth = MetricsAuthenticator(username="test", password="secret")
        
        # Create basic auth header
        credentials = base64.b64encode(b"test:secret").decode()
        auth_header = f"Basic {credentials}"
        
        assert auth._validate_basic_auth(auth_header) is True
    
    def test_basic_auth_validation_failure(self):
        """Test failed basic authentication."""
        auth = MetricsAuthenticator(username="test", password="secret")
        
        # Wrong credentials
        credentials = base64.b64encode(b"test:wrong").decode()
        auth_header = f"Basic {credentials}"
        
        assert auth._validate_basic_auth(auth_header) is False
    
    def test_basic_auth_malformed(self):
        """Test malformed basic auth header."""
        auth = MetricsAuthenticator(username="test", password="secret")
        
        # Malformed header
        auth_header = "Basic malformed"
        
        assert auth._validate_basic_auth(auth_header) is False
    
    def test_api_key_validation_success(self):
        """Test successful API key authentication."""
        api_key = "test-api-key-123"
        auth = MetricsAuthenticator(api_key=api_key)
        
        auth_header = f"Bearer {api_key}"
        
        assert auth._validate_bearer_token(auth_header) is True
    
    def test_api_key_validation_failure(self):
        """Test failed API key authentication."""
        auth = MetricsAuthenticator(api_key="correct-key")
        
        auth_header = "Bearer wrong-key"
        
        assert auth._validate_bearer_token(auth_header) is False
    
    def test_jwt_token_generation(self):
        """Test JWT token generation."""
        jwt_secret = "test-secret"
        auth = MetricsAuthenticator(jwt_secret=jwt_secret)
        
        token = auth.generate_jwt_token()
        
        # Verify token can be decoded
        payload = jwt.decode(token, jwt_secret, algorithms=["HS256"])
        assert payload["sub"] == "metrics"
        assert payload["aud"] == "ml-service"
        assert "exp" in payload
        assert "iat" in payload
    
    def test_jwt_token_validation_success(self):
        """Test successful JWT token validation."""
        jwt_secret = "test-secret"
        auth = MetricsAuthenticator(jwt_secret=jwt_secret)
        
        # Generate token
        token = auth.generate_jwt_token()
        auth_header = f"Bearer {token}"
        
        assert auth._validate_bearer_token(auth_header) is True
    
    def test_jwt_token_validation_expired(self):
        """Test expired JWT token validation."""
        jwt_secret = "test-secret"
        auth = MetricsAuthenticator(jwt_secret=jwt_secret, token_expiry_seconds=1)
        
        # Generate token and wait for expiry
        token = auth.generate_jwt_token()
        time.sleep(2)  # Wait for token to expire
        
        auth_header = f"Bearer {token}"
        
        assert auth._validate_bearer_token(auth_header) is False
    
    def test_rate_limiting(self):
        """Test rate limiting functionality."""
        auth = MetricsAuthenticator()
        auth._max_attempts = 2  # Lower limit for testing
        
        client_ip = "192.168.1.1"
        
        # Should not be rate limited initially
        assert auth._is_rate_limited(client_ip) is False
        
        # Record failed attempts
        auth._record_failed_attempt(client_ip)
        auth._record_failed_attempt(client_ip)
        
        # Should be rate limited now
        assert auth._is_rate_limited(client_ip) is True
        
        # Clear attempts
        auth._clear_failed_attempts(client_ip)
        assert auth._is_rate_limited(client_ip) is False
    
    def test_auth_stats(self):
        """Test authentication statistics."""
        auth = MetricsAuthenticator()
        
        # Record some failed attempts
        auth._record_failed_attempt("192.168.1.1")
        auth._record_failed_attempt("192.168.1.2")
        auth._record_failed_attempt("192.168.1.1")
        
        stats = auth.get_auth_stats()
        
        assert stats["total_failed_attempts"] == 3
        assert stats["unique_failed_ips"] == 2
        assert "max_attempts_before_lockout" in stats
        assert "lockout_duration_seconds" in stats
    
    @patch('ml_service.app.auth.metrics_auth.request')
    def test_authenticate_request_no_auth_header(self, mock_request):
        """Test authentication request without auth header."""
        mock_request.headers.get.return_value = None
        mock_request.environ.get.return_value = "192.168.1.1"
        
        auth = MetricsAuthenticator(username="test", password="secret")
        is_authenticated, error = auth.authenticate_request(mock_request)
        
        assert is_authenticated is False
        assert "Authorization header required" in error
    
    @patch('ml_service.app.auth.metrics_auth.request')
    def test_authenticate_request_basic_auth_success(self, mock_request):
        """Test successful basic auth request."""
        credentials = base64.b64encode(b"test:secret").decode()
        mock_request.headers.get.return_value = f"Basic {credentials}"
        mock_request.environ.get.return_value = "192.168.1.1"
        
        auth = MetricsAuthenticator(username="test", password="secret")
        is_authenticated, error = auth.authenticate_request(mock_request)
        
        assert is_authenticated is True
        assert error is None
    
    @patch('ml_service.app.auth.metrics_auth.request')
    def test_authenticate_request_disabled_auth(self, mock_request):
        """Test authentication when disabled."""
        mock_request.environ.get.return_value = "192.168.1.1"
        
        # No credentials configured - auth should be disabled
        auth = MetricsAuthenticator()
        is_authenticated, error = auth.authenticate_request(mock_request)
        
        assert is_authenticated is True
        assert error is None


class TestMetricsAuthDecorator:
    """Test cases for metrics auth decorator."""
    
    def test_require_metrics_auth_decorator_success(self):
        """Test successful authentication with decorator."""
        app = Flask(__name__)
        
        @app.route('/test')
        @require_metrics_auth
        def test_endpoint():
            return "success"
        
        with app.test_client() as client:
            with patch('ml_service.app.auth.metrics_auth.get_metrics_authenticator') as mock_auth:
                mock_authenticator = MagicMock()
                mock_authenticator.authenticate_request.return_value = (True, None)
                mock_auth.return_value = mock_authenticator
                
                response = client.get('/test')
                assert response.status_code == 200
                assert response.data == b"success"
    
    def test_require_metrics_auth_decorator_failure(self):
        """Test failed authentication with decorator."""
        app = Flask(__name__)
        
        @app.route('/test')
        @require_metrics_auth
        def test_endpoint():
            return "success"
        
        with app.test_client() as client:
            with patch('ml_service.app.auth.metrics_auth.get_metrics_authenticator') as mock_auth:
                mock_authenticator = MagicMock()
                mock_authenticator.authenticate_request.return_value = (False, "Invalid credentials")
                mock_auth.return_value = mock_authenticator
                
                response = client.get('/test')
                assert response.status_code == 401
                assert b"Authentication required" in response.data
                assert "WWW-Authenticate" in response.headers


class TestMetricsAuthUtilities:
    """Test cases for utility functions."""
    
    def test_create_metrics_auth_token(self):
        """Test token creation utility."""
        with patch('ml_service.app.auth.metrics_auth.get_metrics_authenticator') as mock_get_auth:
            mock_authenticator = MagicMock()
            mock_authenticator.generate_jwt_token.return_value = "test-token"
            mock_get_auth.return_value = mock_authenticator
            
            token = create_metrics_auth_token()
            assert token == "test-token"
    
    def test_validate_metrics_request(self):
        """Test request validation utility."""
        with patch('ml_service.app.auth.metrics_auth.get_metrics_authenticator') as mock_get_auth:
            mock_authenticator = MagicMock()
            mock_authenticator.authenticate_request.return_value = (True, None)
            mock_get_auth.return_value = mock_authenticator
            
            is_valid = validate_metrics_request()
            assert is_valid is True
    
    def test_global_authenticator_singleton(self):
        """Test that global authenticator is a singleton."""
        auth1 = get_metrics_authenticator()
        auth2 = get_metrics_authenticator()
        
        assert auth1 is auth2


class TestMetricsAuthIntegration:
    """Integration tests for metrics authentication."""
    
    def test_end_to_end_basic_auth(self):
        """Test end-to-end basic authentication flow."""
        # Create authenticator with test credentials
        auth = MetricsAuthenticator(username="testuser", password="testpass")
        
        # Simulate Flask request object
        class MockRequest:
            def __init__(self, auth_header):
                self.headers = {"Authorization": auth_header}
                self.environ = {"REMOTE_ADDR": "192.168.1.1"}
        
        # Test successful authentication
        credentials = base64.b64encode(b"testuser:testpass").decode()
        request = MockRequest(f"Basic {credentials}")
        
        is_auth, error = auth.authenticate_request(request)
        assert is_auth is True
        assert error is None
        
        # Test failed authentication
        bad_credentials = base64.b64encode(b"testuser:wrongpass").decode()
        bad_request = MockRequest(f"Basic {bad_credentials}")
        
        is_auth, error = auth.authenticate_request(bad_request)
        assert is_auth is False
        assert error is not None
    
    def test_end_to_end_jwt_auth(self):
        """Test end-to-end JWT authentication flow."""
        jwt_secret = "test-jwt-secret"
        auth = MetricsAuthenticator(jwt_secret=jwt_secret)
        
        # Generate token
        token = auth.generate_jwt_token()
        
        # Simulate Flask request object
        class MockRequest:
            def __init__(self, auth_header):
                self.headers = {"Authorization": auth_header}
                self.environ = {"REMOTE_ADDR": "192.168.1.1"}
        
        # Test successful JWT authentication
        request = MockRequest(f"Bearer {token}")
        
        is_auth, error = auth.authenticate_request(request)
        assert is_auth is True
        assert error is None
        
        # Test failed JWT authentication
        bad_request = MockRequest("Bearer invalid-token")
        
        is_auth, error = auth.authenticate_request(bad_request)
        assert is_auth is False
        assert error is not None


if __name__ == "__main__":
    pytest.main([__file__])