"""Common validation utilities to reduce code duplication across the ML service."""

import logging
from typing import Any, Optional, Union, List, Dict, Tuple
from urllib.parse import urlparse

from ..config.constants import (
    DEFAULT_LATITUDE_MIN,
    DEFAULT_LATITUDE_MAX,
    DEFAULT_LONGITUDE_MIN,
    DEFAULT_LONGITUDE_MAX,
    MIN_COLLECTION_INTERVAL,
    MAX_COLLECTION_INTERVAL,
    MAX_COLLECTION_DURATION,
    MAX_COLLECTION_SAMPLES
)


class ValidationError(ValueError):
    """Custom validation error for better error handling."""
    pass


class NumericValidator:
    """Validator for numeric types and ranges."""
    
    @staticmethod
    def validate_numeric_type(
        value: Any, 
        name: str, 
        allow_types: Tuple = (int, float)
    ) -> Union[int, float]:
        """Validate that a value is numeric.
        
        Args:
            value: Value to validate
            name: Name of the parameter for error messages
            allow_types: Allowed numeric types
            
        Returns:
            The validated numeric value
            
        Raises:
            ValidationError: If value is not numeric
        """
        if not isinstance(value, allow_types):
            raise ValidationError(f"{name} must be numeric, got {type(value).__name__}")
        return value
    
    @staticmethod
    def validate_positive(value: Union[int, float], name: str) -> Union[int, float]:
        """Validate that a numeric value is positive.
        
        Args:
            value: Numeric value to validate
            name: Name of the parameter for error messages
            
        Returns:
            The validated positive value
            
        Raises:
            ValidationError: If value is not positive
        """
        if value <= 0:
            raise ValidationError(f"{name} must be positive, got {value}")
        return value
    
    @staticmethod
    def validate_range(
        value: Union[int, float], 
        name: str, 
        min_val: Optional[Union[int, float]] = None,
        max_val: Optional[Union[int, float]] = None
    ) -> Union[int, float]:
        """Validate that a numeric value is within a specified range.
        
        Args:
            value: Numeric value to validate
            name: Name of the parameter for error messages
            min_val: Minimum allowed value (inclusive)
            max_val: Maximum allowed value (inclusive)
            
        Returns:
            The validated value
            
        Raises:
            ValidationError: If value is out of range
        """
        if min_val is not None and value < min_val:
            raise ValidationError(f"{name} must be >= {min_val}, got {value}")
        if max_val is not None and value > max_val:
            raise ValidationError(f"{name} must be <= {max_val}, got {value}")
        return value
    
    @staticmethod
    def validate_numeric_positive_range(
        value: Any,
        name: str,
        min_val: Optional[Union[int, float]] = None,
        max_val: Optional[Union[int, float]] = None,
        allow_types: Tuple = (int, float)
    ) -> Union[int, float]:
        """Combined validation for numeric, positive, and range constraints.
        
        Args:
            value: Value to validate
            name: Name of the parameter for error messages
            min_val: Minimum allowed value (inclusive)
            max_val: Maximum allowed value (inclusive)
            allow_types: Allowed numeric types
            
        Returns:
            The validated value
            
        Raises:
            ValidationError: If any validation fails
        """
        value = NumericValidator.validate_numeric_type(value, name, allow_types)
        if min_val is None or min_val <= 0:
            NumericValidator.validate_positive(value, name)
        NumericValidator.validate_range(value, name, min_val, max_val)
        return value


class StringValidator:
    """Validator for string types and formats."""
    
    @staticmethod
    def validate_string_type(value: Any, name: str) -> str:
        """Validate that a value is a string.
        
        Args:
            value: Value to validate
            name: Name of the parameter for error messages
            
        Returns:
            The validated string value
            
        Raises:
            ValidationError: If value is not a string
        """
        if not isinstance(value, str):
            raise ValidationError(f"{name} must be a string, got {type(value).__name__}")
        return value
    
    @staticmethod
    def validate_non_empty_string(value: Any, name: str) -> str:
        """Validate that a value is a non-empty string.
        
        Args:
            value: Value to validate
            name: Name of the parameter for error messages
            
        Returns:
            The validated non-empty string
            
        Raises:
            ValidationError: If value is not a non-empty string
        """
        value = StringValidator.validate_string_type(value, name)
        if not value.strip():
            raise ValidationError(f"{name} cannot be empty")
        return value
    
    @staticmethod
    def validate_string_length(
        value: str, 
        name: str, 
        min_length: Optional[int] = None,
        max_length: Optional[int] = None
    ) -> str:
        """Validate string length constraints.
        
        Args:
            value: String to validate
            name: Name of the parameter for error messages
            min_length: Minimum allowed length
            max_length: Maximum allowed length
            
        Returns:
            The validated string
            
        Raises:
            ValidationError: If string length is invalid
        """
        length = len(value)
        if min_length is not None and length < min_length:
            raise ValidationError(f"{name} must be at least {min_length} characters, got {length}")
        if max_length is not None and length > max_length:
            raise ValidationError(f"{name} must be at most {max_length} characters, got {length}")
        return value
    
    @staticmethod
    def validate_ue_id(value: Any) -> str:
        """Validate UE ID format.
        
        Args:
            value: UE ID to validate
            
        Returns:
            The validated UE ID
            
        Raises:
            ValidationError: If UE ID is invalid
        """
        return StringValidator.validate_non_empty_string(value, "UE ID")


class GeospatialValidator:
    """Validator for geospatial coordinates and related data."""
    
    @staticmethod
    def validate_latitude(value: Any) -> float:
        """Validate latitude coordinate.
        
        Args:
            value: Latitude value to validate
            
        Returns:
            The validated latitude
            
        Raises:
            ValidationError: If latitude is invalid
        """
        value = NumericValidator.validate_numeric_type(value, "latitude")
        NumericValidator.validate_range(
            value, "latitude", 
            DEFAULT_LATITUDE_MIN, DEFAULT_LATITUDE_MAX
        )
        return float(value)
    
    @staticmethod
    def validate_longitude(value: Any) -> float:
        """Validate longitude coordinate.
        
        Args:
            value: Longitude value to validate
            
        Returns:
            The validated longitude
            
        Raises:
            ValidationError: If longitude is invalid
        """
        value = NumericValidator.validate_numeric_type(value, "longitude")
        NumericValidator.validate_range(
            value, "longitude", 
            DEFAULT_LONGITUDE_MIN, DEFAULT_LONGITUDE_MAX
        )
        return float(value)
    
    @staticmethod
    def validate_position(latitude: Any, longitude: Any) -> Tuple[float, float]:
        """Validate a geographic position (latitude, longitude pair).
        
        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            
        Returns:
            Tuple of validated (latitude, longitude)
            
        Raises:
            ValidationError: If either coordinate is invalid
        """
        lat = GeospatialValidator.validate_latitude(latitude)
        lon = GeospatialValidator.validate_longitude(longitude)
        return lat, lon
    
    @staticmethod
    def validate_altitude(value: Any, allow_none: bool = True) -> Optional[float]:
        """Validate altitude value.
        
        Args:
            value: Altitude value to validate
            allow_none: Whether None values are allowed
            
        Returns:
            The validated altitude or None
            
        Raises:
            ValidationError: If altitude is invalid
        """
        if value is None:
            if allow_none:
                return None
            raise ValidationError("altitude cannot be None")
        
        value = NumericValidator.validate_numeric_type(value, "altitude")
        # Allow reasonable altitude range: -500m to 20,000m
        NumericValidator.validate_range(value, "altitude", -500, 20000)
        return float(value)


class DataCollectionValidator:
    """Validator for data collection parameters."""
    
    @staticmethod
    def validate_collection_duration(value: Any) -> float:
        """Validate data collection duration.
        
        Args:
            value: Duration value to validate
            
        Returns:
            The validated duration
            
        Raises:
            ValidationError: If duration is invalid
        """
        return NumericValidator.validate_numeric_positive_range(
            value, "duration", min_val=0.1, max_val=MAX_COLLECTION_DURATION
        )
    
    @staticmethod
    def validate_collection_interval(value: Any) -> float:
        """Validate data collection interval.
        
        Args:
            value: Interval value to validate
            
        Returns:
            The validated interval
            
        Raises:
            ValidationError: If interval is invalid
        """
        return NumericValidator.validate_numeric_positive_range(
            value, "interval", 
            min_val=MIN_COLLECTION_INTERVAL, 
            max_val=MAX_COLLECTION_INTERVAL
        )
    
    @staticmethod
    def validate_collection_parameters(
        duration: Any, 
        interval: Any
    ) -> Tuple[float, float]:
        """Validate collection duration and interval together.
        
        Args:
            duration: Collection duration
            interval: Collection interval
            
        Returns:
            Tuple of validated (duration, interval)
            
        Raises:
            ValidationError: If parameters are invalid or would generate too many samples
        """
        duration = DataCollectionValidator.validate_collection_duration(duration)
        interval = DataCollectionValidator.validate_collection_interval(interval)
        
        # Check sample count limit
        max_samples = int(duration / interval)
        if max_samples > MAX_COLLECTION_SAMPLES:
            raise ValidationError(
                f"Collection would generate {max_samples} samples "
                f"(max {MAX_COLLECTION_SAMPLES}). "
                f"Increase interval or reduce duration."
            )
        
        return duration, interval


class UEDataValidator:
    """Validator for UE (User Equipment) data structures."""
    
    @staticmethod
    def validate_ue_basic_data(ue_id: Any, ue_data: Any) -> Tuple[str, Dict[str, Any]]:
        """Validate basic UE data structure.
        
        Args:
            ue_id: UE identifier
            ue_data: UE data dictionary
            
        Returns:
            Tuple of validated (ue_id, ue_data)
            
        Raises:
            ValidationError: If UE data is invalid
        """
        ue_id = StringValidator.validate_ue_id(ue_id)
        
        if not isinstance(ue_data, dict):
            raise ValidationError(f"UE data must be a dictionary, got {type(ue_data).__name__}")
        
        return ue_id, ue_data
    
    @staticmethod
    def validate_ue_position_data(ue_data: Dict[str, Any]) -> Tuple[float, float]:
        """Validate UE position data from UE data dictionary.
        
        Args:
            ue_data: UE data dictionary containing position information
            
        Returns:
            Tuple of validated (latitude, longitude)
            
        Raises:
            ValidationError: If position data is missing or invalid
        """
        latitude = ue_data.get("latitude")
        longitude = ue_data.get("longitude")
        
        if latitude is None or longitude is None:
            raise ValidationError("Missing position data (latitude and longitude required)")
        
        return GeospatialValidator.validate_position(latitude, longitude)
    
    @staticmethod
    def validate_cell_id(ue_data: Dict[str, Any]) -> str:
        """Validate Cell ID from UE data.
        
        Args:
            ue_data: UE data dictionary
            
        Returns:
            The validated Cell ID
            
        Raises:
            ValidationError: If Cell ID is missing or invalid
        """
        cell_id = ue_data.get("Cell_id")
        if cell_id is None:
            raise ValidationError("Missing Cell_id in UE data")
        
        return StringValidator.validate_non_empty_string(cell_id, "Cell_id")


class NetworkValidator:
    """Validator for network-related parameters."""
    
    @staticmethod
    def validate_url(value: Any, name: str = "URL") -> str:
        """Validate URL format.
        
        Args:
            value: URL to validate  
            name: Name for error messages
            
        Returns:
            The validated URL
            
        Raises:
            ValidationError: If URL is invalid
        """
        value = StringValidator.validate_non_empty_string(value, name)
        
        try:
            parsed = urlparse(value)
            if not parsed.scheme or not parsed.netloc:
                raise ValidationError(f"Invalid {name} format: missing scheme or netloc")
            if parsed.scheme not in ['http', 'https']:
                raise ValidationError(f"{name} scheme must be http or https")
        except Exception as e:
            raise ValidationError(f"Invalid {name}: {e}") from e
        
        return value
    
    @staticmethod
    def validate_port(value: Any, name: str = "port") -> int:
        """Validate network port number.
        
        Args:
            value: Port number to validate
            name: Name for error messages
            
        Returns:
            The validated port number
            
        Raises:
            ValidationError: If port is invalid
        """
        value = NumericValidator.validate_numeric_type(value, name, (int,))
        NumericValidator.validate_range(value, name, 1, 65535)
        return int(value)


class ValidationHelper:
    """Helper class for common validation patterns with logging."""
    
    def __init__(self, logger_name: Optional[str] = None):
        """Initialize validation helper.
        
        Args:
            logger_name: Name for the logger (defaults to class name)
        """
        self.logger = logging.getLogger(logger_name or __name__)
    
    def log_validation_warning(self, message: str, *args):
        """Log a validation warning message.
        
        Args:
            message: Warning message format string
            *args: Arguments for message formatting
        """
        self.logger.warning(message, *args)
    
    def validate_with_logging(
        self, 
        validator_func, 
        value: Any, 
        context: str,
        *args,
        log_errors: bool = True,
        **kwargs
    ) -> Any:
        """Run validation with optional error logging.
        
        Args:
            validator_func: Validation function to call
            value: Value to validate
            context: Context string for logging
            *args: Arguments to pass to validator
            log_errors: Whether to log validation errors
            **kwargs: Keyword arguments to pass to validator
            
        Returns:
            The validated value or None if validation fails
            
        Raises:
            ValidationError: If validation fails and log_errors is False
        """
        try:
            return validator_func(value, *args, **kwargs)
        except ValidationError as e:
            if log_errors:
                self.log_validation_warning(f"Validation failed for {context}: {e}")
                return None
            raise


# Convenience functions for common validation patterns
def validate_ue_sample_data(ue_id: Any, ue_data: Any, context: str = "UE sample") -> Optional[Tuple[str, Dict[str, Any], float, float]]:
    """Validate UE sample data with position information.
    
    Args:
        ue_id: UE identifier
        ue_data: UE data dictionary
        context: Context for error messages
        
    Returns:
        Tuple of (ue_id, ue_data, latitude, longitude) or None if validation fails
    """
    helper = ValidationHelper()
    
    try:
        ue_id, ue_data = UEDataValidator.validate_ue_basic_data(ue_id, ue_data)
        latitude, longitude = UEDataValidator.validate_ue_position_data(ue_data)
        return ue_id, ue_data, latitude, longitude
    except ValidationError as e:
        helper.log_validation_warning(f"Invalid {context}: {e}")
        return None


def validate_collection_params(duration: Any, interval: Any) -> Optional[Tuple[float, float]]:
    """Validate data collection parameters.
    
    Args:
        duration: Collection duration
        interval: Collection interval
        
    Returns:
        Tuple of (duration, interval) or None if validation fails
    """
    helper = ValidationHelper()
    
    try:
        return DataCollectionValidator.validate_collection_parameters(duration, interval)
    except ValidationError as e:
        helper.log_validation_warning(f"Invalid collection parameters: {e}")
        return None