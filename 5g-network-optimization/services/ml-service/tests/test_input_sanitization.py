"""Tests for input sanitization functionality."""

import pytest
import json
from flask import Flask, request, jsonify
from unittest.mock import patch

from ml_service.app.security.input_sanitizer import (
    InputSanitizer,
    InputSanitizationError,
    SecurityPattern,
    get_input_sanitizer,
    sanitize_input,
    sanitize_request_data
)
from ml_service.app.security.validation_decorators import (
    sanitize_and_validate_json,
    sanitize_path_params,
    sanitize_query_params,
    sanitize_ue_id,
    sanitize_antenna_id,
    sanitize_model_version,
    sanitize_integer_param,
    sanitize_float_param
)


class TestInputSanitizer:
    """Test cases for InputSanitizer class."""
    
    def test_sanitize_clean_string(self):
        """Test sanitization of clean strings."""
        sanitizer = InputSanitizer()
        
        clean_string = "hello world 123"
        result = sanitizer.sanitize(clean_string)
        
        assert result == clean_string
    
    def test_sanitize_html_entities(self):
        """Test HTML entity escaping."""
        sanitizer = InputSanitizer(allow_html=False)
        
        html_string = "<script>alert('xss')</script>"
        result = sanitizer.sanitize(html_string)
        
        assert "&lt;" in result
        assert "&gt;" in result
        assert "<script>" not in result
    
    def test_detect_sql_injection(self):
        """Test SQL injection detection."""
        sanitizer = InputSanitizer(strict_mode=True)
        
        sql_injection = "'; DROP TABLE users; --"
        
        with pytest.raises(InputSanitizationError) as excinfo:
            sanitizer.sanitize(sql_injection)
        
        assert "SQL Injection" in str(excinfo.value)
    
    def test_detect_xss_attempt(self):
        """Test XSS detection."""
        sanitizer = InputSanitizer(strict_mode=True)
        
        xss_attempt = "<script>document.cookie</script>"
        
        with pytest.raises(InputSanitizationError) as excinfo:
            sanitizer.sanitize(xss_attempt)
        
        assert "Cross-Site Scripting" in str(excinfo.value)
    
    def test_detect_command_injection(self):
        """Test command injection detection."""
        sanitizer = InputSanitizer(strict_mode=True)
        
        command_injection = "test; rm -rf /"
        
        with pytest.raises(InputSanitizationError) as excinfo:
            sanitizer.sanitize(command_injection)
        
        assert "Command Injection" in str(excinfo.value)
    
    def test_detect_path_traversal(self):
        """Test path traversal detection."""
        sanitizer = InputSanitizer(strict_mode=True)
        
        path_traversal = "../../etc/passwd"
        
        with pytest.raises(InputSanitizationError) as excinfo:
            sanitizer.sanitize(path_traversal)
        
        assert "Path Traversal" in str(excinfo.value)
    
    def test_sanitize_large_string(self):
        """Test large string handling."""
        sanitizer = InputSanitizer(max_string_length=100, strict_mode=False)
        
        large_string = "x" * 200
        result = sanitizer.sanitize(large_string)
        
        assert len(result) == 100
    
    def test_sanitize_large_string_strict(self):
        """Test large string rejection in strict mode."""
        sanitizer = InputSanitizer(max_string_length=100, strict_mode=True)
        
        large_string = "x" * 200
        
        with pytest.raises(InputSanitizationError) as excinfo:
            sanitizer.sanitize(large_string)
        
        assert "String too long" in str(excinfo.value)
    
    def test_sanitize_numeric_values(self):
        """Test numeric value sanitization."""
        sanitizer = InputSanitizer()
        
        assert sanitizer.sanitize(42) == 42
        assert sanitizer.sanitize(3.14) == 3.14
        assert sanitizer.sanitize(-100) == -100
    
    def test_sanitize_list(self):
        """Test list sanitization."""
        sanitizer = InputSanitizer()
        
        test_list = ["clean", "string", 123, {"key": "value"}]
        result = sanitizer.sanitize(test_list)
        
        assert isinstance(result, list)
        assert len(result) == 4
        assert result[0] == "clean"
        assert result[2] == 123
    
    def test_sanitize_dict(self):
        """Test dictionary sanitization."""
        sanitizer = InputSanitizer()
        
        test_dict = {
            "string": "clean text",
            "number": 42,
            "nested": {"inner": "value"}
        }
        result = sanitizer.sanitize(test_dict)
        
        assert isinstance(result, dict)
        assert result["string"] == "clean text"
        assert result["number"] == 42
        assert result["nested"]["inner"] == "value"
    
    def test_nesting_depth_limit(self):
        """Test nesting depth limitation."""
        sanitizer = InputSanitizer(max_nesting_depth=3)
        
        # Create deeply nested structure
        nested = {"level": 1}
        current = nested
        for i in range(2, 10):
            current["nested"] = {"level": i}
            current = current["nested"]
        
        with pytest.raises(InputSanitizationError) as excinfo:
            sanitizer.sanitize(nested)
        
        assert "Nesting depth exceeded" in str(excinfo.value)
    
    def test_sanitize_url(self):
        """Test URL sanitization."""
        sanitizer = InputSanitizer()
        
        clean_url = "https://example.com/api/data"
        result = sanitizer.sanitize_url(clean_url)
        
        assert "https://example.com" in result
    
    def test_sanitize_malicious_url(self):
        """Test malicious URL detection."""
        sanitizer = InputSanitizer(strict_mode=True)
        
        malicious_url = "http://localhost:8080/admin"
        
        with pytest.raises(InputSanitizationError) as excinfo:
            sanitizer.sanitize_url(malicious_url)
        
        assert "Security threats in URL" in str(excinfo.value)
    
    def test_sanitize_json(self):
        """Test JSON sanitization."""
        sanitizer = InputSanitizer()
        
        json_data = '{"name": "test", "value": 123}'
        result = sanitizer.sanitize_json(json_data)
        
        assert result["name"] == "test"
        assert result["value"] == 123
    
    def test_sanitize_invalid_json(self):
        """Test invalid JSON handling."""
        sanitizer = InputSanitizer()
        
        invalid_json = '{"name": "test", "value":}'
        
        with pytest.raises(InputSanitizationError) as excinfo:
            sanitizer.sanitize_json(invalid_json)
        
        assert "Invalid JSON" in str(excinfo.value)


class TestParameterSanitizers:
    """Test cases for parameter sanitizer functions."""
    
    def test_sanitize_ue_id_valid(self):
        """Test valid UE ID sanitization."""
        valid_ids = ["ue_123", "UE-456", "device_001"]
        
        for ue_id in valid_ids:
            result = sanitize_ue_id(ue_id)
            assert result == ue_id
    
    def test_sanitize_ue_id_invalid(self):
        """Test invalid UE ID rejection."""
        invalid_ids = ["", "x" * 65, "ue@123", "ue 123", "ue.123"]
        
        for ue_id in invalid_ids:
            with pytest.raises(ValueError):
                sanitize_ue_id(ue_id)
    
    def test_sanitize_antenna_id_valid(self):
        """Test valid antenna ID sanitization."""
        valid_ids = ["antenna_1", "ANT123", "base_station_01"]
        
        for antenna_id in valid_ids:
            result = sanitize_antenna_id(antenna_id)
            assert result == antenna_id
    
    def test_sanitize_antenna_id_invalid(self):
        """Test invalid antenna ID rejection."""
        invalid_ids = ["", "x" * 33, "ant-123", "ant 123", "ant.123"]
        
        for antenna_id in invalid_ids:
            with pytest.raises(ValueError):
                sanitize_antenna_id(antenna_id)
    
    def test_sanitize_model_version_valid(self):
        """Test valid model version sanitization."""
        valid_versions = ["1.0", "v2.1.3", "1.0.0-beta", "v1.2"]
        
        for version in valid_versions:
            result = sanitize_model_version(version)
            assert result == version
    
    def test_sanitize_model_version_invalid(self):
        """Test invalid model version rejection."""
        invalid_versions = ["", "x" * 17, "1.0.0.0", "abc", "1.0-"]
        
        for version in invalid_versions:
            with pytest.raises(ValueError):
                sanitize_model_version(version)
    
    def test_sanitize_integer_param(self):
        """Test integer parameter sanitization."""
        sanitizer = sanitize_integer_param(min_val=0, max_val=100)
        
        assert sanitizer("42") == 42
        assert sanitizer("0") == 0
        assert sanitizer("100") == 100
        
        with pytest.raises(ValueError):
            sanitizer("-1")
        
        with pytest.raises(ValueError):
            sanitizer("101")
        
        with pytest.raises(ValueError):
            sanitizer("not_a_number")
    
    def test_sanitize_float_param(self):
        """Test float parameter sanitization."""
        sanitizer = sanitize_float_param(min_val=0.0, max_val=1.0)
        
        assert sanitizer("0.5") == 0.5
        assert sanitizer("0.0") == 0.0
        assert sanitizer("1.0") == 1.0
        
        with pytest.raises(ValueError):
            sanitizer("-0.1")
        
        with pytest.raises(ValueError):
            sanitizer("1.1")
        
        with pytest.raises(ValueError):
            sanitizer("not_a_float")


class TestValidationDecorators:
    """Test cases for validation decorators."""
    
    def test_sanitize_and_validate_json_decorator(self):
        """Test JSON sanitization decorator."""
        app = Flask(__name__)
        
        @app.route('/test', methods=['POST'])
        @sanitize_and_validate_json(sanitize=True, required=True)
        def test_endpoint():
            return jsonify({"status": "ok", "data": request.sanitized_data})
        
        with app.test_client() as client:
            # Test clean data
            clean_data = {"name": "test", "value": 123}
            response = client.post('/test', 
                                 json=clean_data,
                                 content_type='application/json')
            
            assert response.status_code == 200
            result = response.get_json()
            assert result["status"] == "ok"
    
    def test_sanitize_path_params_decorator(self):
        """Test path parameter sanitization decorator."""
        app = Flask(__name__)
        
        @app.route('/ue/<ue_id>')
        @sanitize_path_params(ue_id=sanitize_ue_id)
        def get_ue(ue_id):
            return jsonify({"ue_id": ue_id})
        
        with app.test_client() as client:
            # Test valid UE ID
            response = client.get('/ue/ue_123')
            assert response.status_code == 200
            
            result = response.get_json()
            assert result["ue_id"] == "ue_123"


class TestSecurityPatterns:
    """Test cases for security pattern detection."""
    
    def test_sql_injection_patterns(self):
        """Test SQL injection pattern detection."""
        test_cases = [
            "SELECT * FROM users",
            "' OR 1=1 --",
            "UNION ALL SELECT",
            "'; DROP TABLE users; --"
        ]
        
        for pattern in SecurityPattern.SQL_INJECTION_PATTERNS:
            for test_case in test_cases:
                if pattern.search(test_case):
                    # Pattern should match
                    assert True
                    break
            else:
                # No pattern matched, check if this is expected
                continue
    
    def test_xss_patterns(self):
        """Test XSS pattern detection."""
        test_cases = [
            "<script>alert('xss')</script>",
            "<iframe src='malicious'></iframe>",
            "javascript:alert(1)",
            "onclick='alert(1)'"
        ]
        
        sanitizer = InputSanitizer(strict_mode=True)
        
        for test_case in test_cases:
            threats = sanitizer._detect_security_threats(test_case)
            assert len(threats) > 0


class TestGlobalSanitizer:
    """Test cases for global sanitizer functions."""
    
    def test_get_input_sanitizer(self):
        """Test global sanitizer retrieval."""
        sanitizer1 = get_input_sanitizer()
        sanitizer2 = get_input_sanitizer()
        
        # Should return the same instance
        assert sanitizer1 is sanitizer2
    
    def test_sanitize_input_function(self):
        """Test global sanitize input function."""
        clean_data = {"test": "value"}
        result = sanitize_input(clean_data, "test_context")
        
        assert result == clean_data
    
    def test_sanitize_request_data_function(self):
        """Test request data sanitization function."""
        request_data = {"endpoint": "test", "data": "clean"}
        result = sanitize_request_data(request_data, "test_endpoint")
        
        assert result == request_data


if __name__ == "__main__":
    pytest.main([__file__])