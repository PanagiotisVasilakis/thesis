"""Authentication and authorization for metrics endpoint."""

import base64
import hmac
import hashlib
import time
import os
import logging
from typing import Optional, Tuple
from functools import wraps
from flask import request, Response, current_app
import jwt

from ..utils.exception_handler import SecurityError
from ..config.constants import env_constants


logger = logging.getLogger(__name__)


class MetricsAuthError(SecurityError):
    """Authentication error for metrics endpoint."""
    pass


class MetricsAuthenticator:
    """Handles authentication for the metrics endpoint."""
    
    def __init__(self, 
                 username: Optional[str] = None,
                 password: Optional[str] = None,
                 api_key: Optional[str] = None,
                 jwt_secret: Optional[str] = None,
                 token_expiry_seconds: int = 3600):
        """Initialize metrics authenticator.
        
        Args:
            username: Basic auth username
            password: Basic auth password  
            api_key: API key for Bearer token auth
            jwt_secret: JWT secret for token generation
            token_expiry_seconds: JWT token expiry time
        """
        self.username = username or env_constants.METRICS_AUTH_USERNAME
        self.password = password or env_constants.METRICS_AUTH_PASSWORD
        self.api_key = api_key or env_constants.METRICS_API_KEY
        self.jwt_secret = jwt_secret or env_constants.JWT_SECRET
        self.token_expiry_seconds = token_expiry_seconds
        
        # Track failed authentication attempts for rate limiting
        self._failed_attempts = {}
        self._max_attempts = 5
        self._lockout_duration = 300  # 5 minutes
        
    def _is_rate_limited(self, client_ip: str) -> bool:
        """Check if client IP is rate limited due to failed attempts."""
        if client_ip not in self._failed_attempts:
            return False
        
        attempts, last_attempt = self._failed_attempts[client_ip]
        
        # Reset counter if lockout period has passed
        if time.time() - last_attempt > self._lockout_duration:
            del self._failed_attempts[client_ip]
            return False
        
        return attempts >= self._max_attempts
    
    def _record_failed_attempt(self, client_ip: str) -> None:
        """Record a failed authentication attempt."""
        now = time.time()
        if client_ip in self._failed_attempts:
            attempts, _ = self._failed_attempts[client_ip]
            self._failed_attempts[client_ip] = (attempts + 1, now)
        else:
            self._failed_attempts[client_ip] = (1, now)
    
    def _clear_failed_attempts(self, client_ip: str) -> None:
        """Clear failed attempts for successful authentication."""
        if client_ip in self._failed_attempts:
            del self._failed_attempts[client_ip]
    
    def _validate_basic_auth(self, auth_header: str) -> bool:
        """Validate HTTP Basic Authentication."""
        try:
            # Remove 'Basic ' prefix
            encoded_credentials = auth_header[6:]
            decoded = base64.b64decode(encoded_credentials).decode('utf-8')
            username, password = decoded.split(':', 1)
            
            # Use secure comparison to prevent timing attacks
            username_match = hmac.compare_digest(username, self.username or "")
            password_match = hmac.compare_digest(password, self.password or "")
            
            return username_match and password_match and self.username and self.password
            
        except Exception as e:
            logger.warning("Basic auth validation error: %s", e)
            return False
    
    def _validate_bearer_token(self, auth_header: str) -> bool:
        """Validate Bearer token (API key or JWT)."""
        try:
            # Remove 'Bearer ' prefix
            token = auth_header[7:]
            
            # Try API key validation first
            if self.api_key and hmac.compare_digest(token, self.api_key):
                return True
            
            # Try JWT validation
            if self.jwt_secret:
                try:
                    payload = jwt.decode(
                        token,
                        self.jwt_secret,
                        algorithms=["HS256"],
                        options={"require_exp": True}
                    )
                    
                    # Validate required claims
                    if payload.get("sub") == "metrics" and payload.get("aud") == "ml-service":
                        return True
                        
                except jwt.ExpiredSignatureError:
                    logger.warning("JWT token expired")
                except jwt.InvalidTokenError as e:
                    logger.warning("Invalid JWT token: %s", e)
            
            return False
            
        except Exception as e:
            logger.warning("Bearer token validation error: %s", e)
            return False
    
    def authenticate_request(self, request_obj=None) -> Tuple[bool, Optional[str]]:
        """Authenticate a request for metrics access.
        
        Args:
            request_obj: Flask request object (uses current request if None)
            
        Returns:
            Tuple of (is_authenticated, error_message)
        """
        if request_obj is None:
            request_obj = request
        
        client_ip = request_obj.environ.get('REMOTE_ADDR', 'unknown')
        
        # Check rate limiting
        if self._is_rate_limited(client_ip):
            logger.warning("Rate limited metrics access attempt from %s", client_ip)
            return False, "Too many failed authentication attempts. Try again later."
        
        # Check if authentication is disabled (development mode)
        if not any([self.username, self.password, self.api_key, self.jwt_secret]):
            logger.warning("Metrics authentication is disabled - no credentials configured")
            return True, None
        
        # Check for Authorization header
        auth_header = request_obj.headers.get('Authorization')
        if not auth_header:
            self._record_failed_attempt(client_ip)
            return False, "Authorization header required"
        
        # Validate authentication method
        is_authenticated = False
        
        if auth_header.startswith('Basic '):
            is_authenticated = self._validate_basic_auth(auth_header)
        elif auth_header.startswith('Bearer '):
            is_authenticated = self._validate_bearer_token(auth_header)
        else:
            self._record_failed_attempt(client_ip)
            return False, "Unsupported authentication method"
        
        if is_authenticated:
            self._clear_failed_attempts(client_ip)
            logger.info("Successful metrics authentication from %s", client_ip)
            return True, None
        else:
            self._record_failed_attempt(client_ip)
            logger.warning("Failed metrics authentication from %s", client_ip)
            return False, "Invalid credentials"
    
    def generate_jwt_token(self, subject: str = "metrics", audience: str = "ml-service") -> str:
        """Generate a JWT token for metrics access.
        
        Args:
            subject: Token subject
            audience: Token audience
            
        Returns:
            JWT token string
        """
        if not self.jwt_secret:
            raise MetricsAuthError("JWT secret not configured")
        
        payload = {
            "sub": subject,
            "aud": audience,
            "iat": int(time.time()),
            "exp": int(time.time()) + self.token_expiry_seconds,
            "iss": "ml-service"
        }
        
        return jwt.encode(payload, self.jwt_secret, algorithm="HS256")
    
    def get_auth_stats(self) -> dict:
        """Get authentication statistics."""
        total_failed = sum(attempts for attempts, _ in self._failed_attempts.values())
        locked_ips = sum(1 for ip in self._failed_attempts.keys() if self._is_rate_limited(ip))
        
        return {
            "total_failed_attempts": total_failed,
            "unique_failed_ips": len(self._failed_attempts),
            "currently_locked_ips": locked_ips,
            "max_attempts_before_lockout": self._max_attempts,
            "lockout_duration_seconds": self._lockout_duration
        }


# Global authenticator instance
_metrics_authenticator: Optional[MetricsAuthenticator] = None


def get_metrics_authenticator() -> MetricsAuthenticator:
    """Get or create the global metrics authenticator."""
    global _metrics_authenticator
    
    if _metrics_authenticator is None:
        _metrics_authenticator = MetricsAuthenticator()
    
    return _metrics_authenticator


def require_metrics_auth(f):
    """Decorator to require authentication for metrics endpoints."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth = get_metrics_authenticator()
        is_authenticated, error_message = auth.authenticate_request()
        
        if not is_authenticated:
            response = Response(
                f"Authentication required: {error_message}",
                status=401,
                headers={
                    'WWW-Authenticate': 'Basic realm="Metrics", Bearer'
                }
            )
            return response
        
        return f(*args, **kwargs)
    
    return decorated_function


def create_metrics_auth_token() -> str:
    """Create a JWT token for metrics access."""
    auth = get_metrics_authenticator()
    return auth.generate_jwt_token()


def validate_metrics_request(request_obj=None) -> bool:
    """Validate a metrics request without decorators."""
    auth = get_metrics_authenticator()
    is_authenticated, _ = auth.authenticate_request(request_obj)
    return is_authenticated