"""Input sanitization and security validation for the ML service."""

import re
import html
import json
import logging
import unicodedata
from typing import Any, Dict, List, Optional, Union, Callable, Pattern
from urllib.parse import urlparse, quote
from pathlib import Path
import base64

from ..utils.exception_handler import SecurityError
from ..config.constants import env_constants


logger = logging.getLogger(__name__)


class InputSanitizationError(SecurityError):
    """Raised when input sanitization fails or detects security issues."""
    pass


class SecurityPattern:
    """Container for security patterns and validation rules."""
    
    # Common injection patterns
    SQL_INJECTION_PATTERNS = [
        re.compile(r"(\b(union|select|insert|update|delete|drop|create|alter|exec|execute|script)\b)", re.IGNORECASE),
        re.compile(r"(\b(union|select)\s+(null|[\w\s,*])+\s+from\b)", re.IGNORECASE),
        re.compile(r"(\bunion\s+all\s+select\b)", re.IGNORECASE),
        re.compile(r"(\b(or|and)\s+\d+\s*=\s*\d+\b)", re.IGNORECASE),
        re.compile(r"(\b(or|and)\s+(true|false)\b)", re.IGNORECASE),
        re.compile(r"(\b(sleep|waitfor|delay)\s*\(\s*\d+\s*\)\b)", re.IGNORECASE),
        re.compile(r"(--|\#|\/\*|\*\/)", re.IGNORECASE),
    ]
    
    # XSS patterns
    XSS_PATTERNS = [
        re.compile(r"<\s*script[^>]*>.*?</\s*script\s*>", re.IGNORECASE | re.DOTALL),
        re.compile(r"<\s*iframe[^>]*>.*?</\s*iframe\s*>", re.IGNORECASE | re.DOTALL),
        re.compile(r"<\s*object[^>]*>.*?</\s*object\s*>", re.IGNORECASE | re.DOTALL),
        re.compile(r"<\s*embed[^>]*>.*?</\s*embed\s*>", re.IGNORECASE | re.DOTALL),
        re.compile(r"<\s*link[^>]*>", re.IGNORECASE),
        re.compile(r"<\s*meta[^>]*>", re.IGNORECASE),
        re.compile(r"javascript\s*:", re.IGNORECASE),
        re.compile(r"vbscript\s*:", re.IGNORECASE),
        re.compile(r"data\s*:", re.IGNORECASE),
        re.compile(r"on\w+\s*=", re.IGNORECASE),  # Event handlers
        re.compile(r"expression\s*\(", re.IGNORECASE),  # CSS expressions
    ]
    
    # Command injection patterns
    COMMAND_INJECTION_PATTERNS = [
        re.compile(r"(\||&&|;|`|\$\(|\${)", re.IGNORECASE),
        re.compile(r"(sudo|su|passwd|chmod|chown|rm|mv|cp|cat|grep|awk|sed|tar|zip|unzip)", re.IGNORECASE),
        re.compile(r"(sh|bash|zsh|csh|tcsh|fish|dash)", re.IGNORECASE),
        re.compile(r"(curl|wget|nc|netcat|telnet|ssh|ftp)", re.IGNORECASE),
        re.compile(r"(\\\\|\.\.\/|\.\.\\)", re.IGNORECASE),  # Path traversal
    ]
    
    # LDAP injection patterns
    LDAP_INJECTION_PATTERNS = [
        re.compile(r"(\(|\)|\*|\||&|!)", re.IGNORECASE),
        re.compile(r"(cn=|ou=|dc=|uid=)", re.IGNORECASE),
    ]
    
    # NoSQL injection patterns
    NOSQL_INJECTION_PATTERNS = [
        re.compile(r"(\$where|\$ne|\$gt|\$lt|\$gte|\$lte|\$in|\$nin|\$regex|\$exists)", re.IGNORECASE),
        re.compile(r"(function\s*\(|\$function|\$eval)", re.IGNORECASE),
    ]
    
    # File path traversal patterns
    PATH_TRAVERSAL_PATTERNS = [
        re.compile(r"(\.\.\/|\.\.\\|%2e%2e%2f|%2e%2e%5c)", re.IGNORECASE),
        re.compile(r"(\/etc\/|\/proc\/|\/sys\/|\/dev\/|\/tmp\/|\/var\/)", re.IGNORECASE),
        re.compile(r"(windows\\system32|windows\\temp|program files)", re.IGNORECASE),
    ]
    
    # SSRF patterns
    SSRF_PATTERNS = [
        re.compile(r"(localhost|127\.0\.0\.1|0\.0\.0\.0|::1|0:0:0:0:0:0:0:1)", re.IGNORECASE),
        re.compile(r"(169\.254\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.)", re.IGNORECASE),
        re.compile(r"(file:\/\/|ftp:\/\/|gopher:\/\/|dict:\/\/)", re.IGNORECASE),
    ]
    
    # Dangerous characters that should be escaped or removed
    DANGEROUS_CHARS = {
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#x27;',
        '&': '&amp;',
        '\x00': '',  # Null byte
        '\x0b': '',  # Vertical tab
        '\x0c': '',  # Form feed
    }


class InputSanitizer:
    """Comprehensive input sanitization and validation."""
    
    def __init__(self,
                 strict_mode: bool = False,
                 max_string_length: int = 10000,
                 max_list_size: int = 1000,
                 max_dict_size: int = 1000,
                 max_nesting_depth: int = 10,
                 allow_html: bool = False,
                 custom_patterns: Optional[List[Pattern]] = None):
        """Initialize input sanitizer.
        
        Args:
            strict_mode: Enable strict security validation
            max_string_length: Maximum allowed string length
            max_list_size: Maximum allowed list size
            max_dict_size: Maximum allowed dictionary size
            max_nesting_depth: Maximum allowed nesting depth
            allow_html: Whether to allow HTML content
            custom_patterns: Additional custom security patterns
        """
        self.strict_mode = strict_mode
        self.max_string_length = max_string_length
        self.max_list_size = max_list_size
        self.max_dict_size = max_dict_size
        self.max_nesting_depth = max_nesting_depth
        self.allow_html = allow_html
        self.custom_patterns = custom_patterns or []
        
        # Compile all security patterns
        self.security_patterns = (
            SecurityPattern.SQL_INJECTION_PATTERNS +
            SecurityPattern.XSS_PATTERNS +
            SecurityPattern.COMMAND_INJECTION_PATTERNS +
            SecurityPattern.LDAP_INJECTION_PATTERNS +
            SecurityPattern.NOSQL_INJECTION_PATTERNS +
            SecurityPattern.PATH_TRAVERSAL_PATTERNS +
            SecurityPattern.SSRF_PATTERNS +
            self.custom_patterns
        )
    
    def _detect_security_threats(self, text: str, context: str = "") -> List[str]:
        """Detect potential security threats in text.
        
        Args:
            text: Text to scan
            context: Context for error reporting
            
        Returns:
            List of detected threat descriptions
        """
        threats = []
        
        for pattern in self.security_patterns:
            matches = pattern.findall(text)
            if matches:
                threat_type = "Unknown"
                
                # Identify threat type based on pattern
                if pattern in SecurityPattern.SQL_INJECTION_PATTERNS:
                    threat_type = "SQL Injection"
                elif pattern in SecurityPattern.XSS_PATTERNS:
                    threat_type = "Cross-Site Scripting (XSS)"
                elif pattern in SecurityPattern.COMMAND_INJECTION_PATTERNS:
                    threat_type = "Command Injection"
                elif pattern in SecurityPattern.LDAP_INJECTION_PATTERNS:
                    threat_type = "LDAP Injection"
                elif pattern in SecurityPattern.NOSQL_INJECTION_PATTERNS:
                    threat_type = "NoSQL Injection"
                elif pattern in SecurityPattern.PATH_TRAVERSAL_PATTERNS:
                    threat_type = "Path Traversal"
                elif pattern in SecurityPattern.SSRF_PATTERNS:
                    threat_type = "Server-Side Request Forgery (SSRF)"
                
                threats.append(f"{threat_type}: {matches[0]}")
        
        return threats
    
    def _sanitize_string(self, value: str, context: str = "") -> str:
        """Sanitize a string value.
        
        Args:
            value: String to sanitize
            context: Context for error reporting
            
        Returns:
            Sanitized string
        """
        if not isinstance(value, str):
            raise InputSanitizationError(f"Expected string, got {type(value).__name__} in {context}")
        
        # Check length limits
        if len(value) > self.max_string_length:
            if self.strict_mode:
                raise InputSanitizationError(
                    f"String too long in {context}: {len(value)} > {self.max_string_length}"
                )
            value = value[:self.max_string_length]
            logger.warning("Truncated oversized string in %s", context)
        
        # Normalize Unicode
        value = unicodedata.normalize('NFKC', value)
        
        # Remove control characters (except tab, newline, carriage return)
        value = ''.join(char for char in value if ord(char) >= 32 or char in '\t\n\r')
        
        # Detect security threats
        if self.strict_mode:
            threats = self._detect_security_threats(value, context)
            if threats:
                raise InputSanitizationError(
                    f"Security threats detected in {context}: {', '.join(threats)}"
                )
        
        # HTML sanitization - escape entities to prevent HTML injection.
        # Using ``html.escape`` avoids double-escaping issues when replacing
        # characters sequentially (e.g. ``<`` becoming ``&amp;lt;``).
        value = html.escape(value, quote=True)
        return value
    
    def _sanitize_numeric(self, value: Union[int, float], context: str = "") -> Union[int, float]:
        """Sanitize numeric values.
        
        Args:
            value: Numeric value to sanitize
            context: Context for error reporting
            
        Returns:
            Sanitized numeric value
        """
        if not isinstance(value, (int, float)):
            raise InputSanitizationError(f"Expected numeric value, got {type(value).__name__} in {context}")
        
        # Check for special float values
        if isinstance(value, float):
            if not (-1e308 <= value <= 1e308):  # IEEE 754 double precision range
                raise InputSanitizationError(f"Float value out of range in {context}: {value}")
            
            # Check for NaN and infinity
            import math
            if math.isnan(value) or math.isinf(value):
                if self.strict_mode:
                    raise InputSanitizationError(f"Invalid float value in {context}: {value}")
                return 0.0  # Default fallback
        
        # Check integer bounds
        if isinstance(value, int):
            if not (-2**63 <= value <= 2**63 - 1):  # 64-bit signed integer range
                raise InputSanitizationError(f"Integer value out of range in {context}: {value}")
        
        return value
    
    def _sanitize_list(self, value: List[Any], context: str = "", depth: int = 0) -> List[Any]:
        """Sanitize list values.
        
        Args:
            value: List to sanitize
            context: Context for error reporting
            depth: Current nesting depth
            
        Returns:
            Sanitized list
        """
        if not isinstance(value, list):
            raise InputSanitizationError(f"Expected list, got {type(value).__name__} in {context}")
        
        # Check depth limits
        if depth > self.max_nesting_depth:
            raise InputSanitizationError(f"Nesting depth exceeded in {context}: {depth} > {self.max_nesting_depth}")
        
        # Check size limits
        if len(value) > self.max_list_size:
            if self.strict_mode:
                raise InputSanitizationError(
                    f"List too large in {context}: {len(value)} > {self.max_list_size}"
                )
            value = value[:self.max_list_size]
            logger.warning("Truncated oversized list in %s", context)
        
        # Recursively sanitize elements
        sanitized = []
        for i, item in enumerate(value):
            item_context = f"{context}[{i}]"
            sanitized.append(self.sanitize(item, item_context, depth + 1))
        
        return sanitized
    
    def _sanitize_dict(self, value: Dict[str, Any], context: str = "", depth: int = 0) -> Dict[str, Any]:
        """Sanitize dictionary values.
        
        Args:
            value: Dictionary to sanitize
            context: Context for error reporting
            depth: Current nesting depth
            
        Returns:
            Sanitized dictionary
        """
        if not isinstance(value, dict):
            raise InputSanitizationError(f"Expected dict, got {type(value).__name__} in {context}")
        
        # Check depth limits
        if depth > self.max_nesting_depth:
            raise InputSanitizationError(f"Nesting depth exceeded in {context}: {depth} > {self.max_nesting_depth}")
        
        # Check size limits
        if len(value) > self.max_dict_size:
            if self.strict_mode:
                raise InputSanitizationError(
                    f"Dictionary too large in {context}: {len(value)} > {self.max_dict_size}"
                )
            # Keep only first N items
            items = list(value.items())[:self.max_dict_size]
            value = dict(items)
            logger.warning("Truncated oversized dictionary in %s", context)
        
        # Recursively sanitize keys and values
        sanitized = {}
        for key, val in value.items():
            # Sanitize key
            if not isinstance(key, str):
                if self.strict_mode:
                    raise InputSanitizationError(f"Non-string key in {context}: {key}")
                key = str(key)
            
            key_context = f"{context}.{key}"
            sanitized_key = self._sanitize_string(key, key_context)
            
            # Sanitize value
            sanitized_value = self.sanitize(val, key_context, depth + 1)
            sanitized[sanitized_key] = sanitized_value
        
        return sanitized
    
    def sanitize(self, value: Any, context: str = "", depth: int = 0) -> Any:
        """Sanitize any input value.
        
        Args:
            value: Value to sanitize
            context: Context for error reporting
            depth: Current nesting depth
            
        Returns:
            Sanitized value
        """
        try:
            if value is None:
                return None
            elif isinstance(value, bool):
                return value
            elif isinstance(value, str):
                return self._sanitize_string(value, context)
            elif isinstance(value, (int, float)):
                return self._sanitize_numeric(value, context)
            elif isinstance(value, list):
                return self._sanitize_list(value, context, depth)
            elif isinstance(value, dict):
                return self._sanitize_dict(value, context, depth)
            else:
                if self.strict_mode:
                    raise InputSanitizationError(f"Unsupported type in {context}: {type(value).__name__}")
                logger.warning("Converting unsupported type %s to string in %s", type(value).__name__, context)
                return self._sanitize_string(str(value), context)
        
        except Exception as e:
            if isinstance(e, InputSanitizationError):
                raise
            raise InputSanitizationError(f"Sanitization failed in {context}: {e}") from e
    
    def sanitize_url(self, url: str, allowed_schemes: Optional[List[str]] = None) -> str:
        """Sanitize URL inputs.
        
        Args:
            url: URL to sanitize
            allowed_schemes: List of allowed URL schemes
            
        Returns:
            Sanitized URL
        """
        if not isinstance(url, str):
            raise InputSanitizationError(f"Expected string URL, got {type(url).__name__}")
        
        # Basic length check
        if len(url) > 2048:  # RFC compliant URL length
            raise InputSanitizationError(f"URL too long: {len(url)} > 2048")
        
        try:
            parsed = urlparse(url)
        except Exception as e:
            raise InputSanitizationError(f"Invalid URL format: {e}") from e
        
        # Check allowed schemes
        if allowed_schemes is None:
            allowed_schemes = ['http', 'https']
        
        if parsed.scheme.lower() not in allowed_schemes:
            raise InputSanitizationError(f"Disallowed URL scheme: {parsed.scheme}")
        
        # Check for SSRF attempts
        if self.strict_mode:
            threats = self._detect_security_threats(url, "URL")
            if threats:
                raise InputSanitizationError(f"Security threats in URL: {', '.join(threats)}")
        
        # Encode potentially dangerous characters
        return quote(url, safe=':/?#[]@!$&\'()*+,;=')
    
    def sanitize_file_path(self, path: str, allowed_extensions: Optional[List[str]] = None) -> str:
        """Sanitize file path inputs.
        
        Args:
            path: File path to sanitize
            allowed_extensions: List of allowed file extensions
            
        Returns:
            Sanitized file path
        """
        if not isinstance(path, str):
            raise InputSanitizationError(f"Expected string path, got {type(path).__name__}")
        
        # Basic length check
        if len(path) > 1024:
            raise InputSanitizationError(f"Path too long: {len(path)} > 1024")
        
        # Check for path traversal attempts
        if self.strict_mode:
            threats = self._detect_security_threats(path, "file path")
            if threats:
                raise InputSanitizationError(f"Security threats in file path: {', '.join(threats)}")
        
        try:
            # Normalize path
            normalized_path = Path(path).resolve()
            path_str = str(normalized_path)
        except Exception as e:
            raise InputSanitizationError(f"Invalid file path: {e}") from e
        
        # Check file extension if specified
        if allowed_extensions:
            extension = Path(path).suffix.lower()
            if extension not in allowed_extensions:
                raise InputSanitizationError(f"Disallowed file extension: {extension}")
        
        return path_str
    
    def sanitize_json(self, json_str: str, max_size: int = 1024 * 1024) -> Any:
        """Sanitize JSON input.
        
        Args:
            json_str: JSON string to sanitize
            max_size: Maximum JSON size in bytes
            
        Returns:
            Sanitized parsed JSON data
        """
        if not isinstance(json_str, str):
            raise InputSanitizationError(f"Expected string JSON, got {type(json_str).__name__}")
        
        # Check size limits
        if len(json_str.encode('utf-8')) > max_size:
            raise InputSanitizationError(f"JSON too large: {len(json_str)} > {max_size}")
        
        try:
            # Parse JSON with strict parsing
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise InputSanitizationError(f"Invalid JSON: {e}") from e
        
        # Sanitize the parsed data
        return self.sanitize(data, "JSON")
    
    def get_sanitization_stats(self) -> Dict[str, Any]:
        """Get sanitization configuration statistics.
        
        Returns:
            Dictionary containing sanitization stats
        """
        return {
            "strict_mode": self.strict_mode,
            "max_string_length": self.max_string_length,
            "max_list_size": self.max_list_size,
            "max_dict_size": self.max_dict_size,
            "max_nesting_depth": self.max_nesting_depth,
            "allow_html": self.allow_html,
            "security_patterns_count": len(self.security_patterns),
            "custom_patterns_count": len(self.custom_patterns)
        }


# Global sanitizer instance
_global_sanitizer: Optional[InputSanitizer] = None


def get_input_sanitizer() -> InputSanitizer:
    """Get or create the global input sanitizer."""
    global _global_sanitizer
    
    if _global_sanitizer is None:
        _global_sanitizer = InputSanitizer(
            strict_mode=env_constants.INPUT_SANITIZER_STRICT_MODE,
            max_string_length=env_constants.INPUT_MAX_STRING_LENGTH,
            max_list_size=env_constants.INPUT_MAX_LIST_SIZE,
            max_dict_size=env_constants.INPUT_MAX_DICT_SIZE,
            max_nesting_depth=env_constants.INPUT_MAX_NESTING_DEPTH,
            allow_html=env_constants.INPUT_ALLOW_HTML
        )
    
    return _global_sanitizer


def sanitize_input(value: Any, context: str = "") -> Any:
    """Sanitize any input value using the global sanitizer.
    
    Args:
        value: Value to sanitize
        context: Context for error reporting
        
    Returns:
        Sanitized value
    """
    sanitizer = get_input_sanitizer()
    return sanitizer.sanitize(value, context)


def sanitize_request_data(data: Any, endpoint: str = "") -> Any:
    """Sanitize request data for API endpoints.
    
    Args:
        data: Request data to sanitize
        endpoint: API endpoint name for context
        
    Returns:
        Sanitized request data
    """
    context = f"API endpoint {endpoint}" if endpoint else "API request"
    return sanitize_input(data, context)