#!/usr/bin/env python3
"""
Administrative script for managing metrics authentication.

This script provides utilities for:
- Generating secure API keys for metrics access
- Creating JWT tokens for temporary access
- Testing authentication credentials
- Managing authentication configuration

Usage examples:
    python metrics_auth_admin.py generate-api-key
    python metrics_auth_admin.py create-token --duration 3600
    python metrics_auth_admin.py test-auth --username metrics --password secret
    python metrics_auth_admin.py validate-config
"""

import argparse
import os
import sys
import secrets
import base64
import time
import logging
from typing import Optional

# Add the parent directory to the path so we can import ML service modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from ml_service.app.auth.metrics_auth import MetricsAuthenticator, MetricsAuthError
from ml_service.app.config.constants import env_constants


def generate_api_key(length: int = 32) -> str:
    """Generate a cryptographically secure API key.
    
    Args:
        length: Length of the API key in bytes
        
    Returns:
        Base64-encoded API key
    """
    key_bytes = secrets.token_bytes(length)
    return base64.urlsafe_b64encode(key_bytes).decode('ascii').rstrip('=')


def generate_password(length: int = 16) -> str:
    """Generate a secure password.
    
    Args:
        length: Length of the password
        
    Returns:
        Generated password
    """
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def create_jwt_token(
    duration: int = 3600,
    username: Optional[str] = None,
    password: Optional[str] = None,
    api_key: Optional[str] = None,
    jwt_secret: Optional[str] = None
) -> str:
    """Create a JWT token for metrics access.
    
    Args:
        duration: Token duration in seconds
        username: Basic auth username
        password: Basic auth password
        api_key: API key for authentication
        jwt_secret: JWT secret for signing
        
    Returns:
        JWT token string
    """
    authenticator = MetricsAuthenticator(
        username=username,
        password=password,
        api_key=api_key,
        jwt_secret=jwt_secret,
        token_expiry_seconds=duration
    )
    
    return authenticator.generate_jwt_token()


def test_authentication(
    username: Optional[str] = None,
    password: Optional[str] = None,
    api_key: Optional[str] = None,
    jwt_secret: Optional[str] = None
) -> bool:
    """Test authentication configuration.
    
    Args:
        username: Basic auth username
        password: Basic auth password
        api_key: API key for authentication  
        jwt_secret: JWT secret for signing
        
    Returns:
        True if authentication configuration is valid
    """
    try:
        authenticator = MetricsAuthenticator(
            username=username,
            password=password,
            api_key=api_key,
            jwt_secret=jwt_secret
        )
        
        # Test JWT token generation if JWT secret is provided
        if jwt_secret:
            token = authenticator.generate_jwt_token()
            print(f"✓ JWT token generation successful: {token[:20]}...")
        
        # Test basic auth validation if credentials are provided
        if username and password:
            import base64
            credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
            auth_header = f"Basic {credentials}"
            
            is_valid = authenticator._validate_basic_auth(auth_header)
            if is_valid:
                print("✓ Basic authentication validation successful")
            else:
                print("✗ Basic authentication validation failed")
                return False
        
        # Test API key validation if provided
        if api_key:
            auth_header = f"Bearer {api_key}"
            is_valid = authenticator._validate_bearer_token(auth_header)
            if is_valid:
                print("✓ API key validation successful")
            else:
                print("✗ API key validation failed")
                return False
        
        return True
        
    except Exception as e:
        print(f"✗ Authentication test failed: {e}")
        return False


def validate_configuration() -> bool:
    """Validate the current metrics authentication configuration.
    
    Returns:
        True if configuration is valid
    """
    print("Validating metrics authentication configuration...")
    print()
    
    # Check environment variables
    config_items = [
        ("METRICS_AUTH_ENABLED", env_constants.METRICS_AUTH_ENABLED),
        ("METRICS_AUTH_USERNAME", env_constants.METRICS_AUTH_USERNAME),
        ("METRICS_AUTH_PASSWORD", env_constants.METRICS_AUTH_PASSWORD),
        ("METRICS_API_KEY", env_constants.METRICS_API_KEY),
        ("JWT_SECRET", env_constants.JWT_SECRET),
    ]
    
    missing_configs = []
    for name, value in config_items:
        if value is None:
            status = "❌ NOT SET"
            missing_configs.append(name)
        else:
            status = "✓ SET" if isinstance(value, bool) else f"✓ SET ({len(str(value))} chars)"
        
        print(f"{name:25} {status}")
    
    print()
    
    if not env_constants.METRICS_AUTH_ENABLED:
        print("⚠️  Metrics authentication is DISABLED")
        print("   Set METRICS_AUTH_ENABLED=true to enable authentication")
        return True
    
    if missing_configs:
        print("❌ Missing required configuration:")
        for config in missing_configs:
            print(f"   - {config}")
        print()
        print("At least one of the following must be set:")
        print("   - METRICS_AUTH_USERNAME and METRICS_AUTH_PASSWORD (for Basic auth)")
        print("   - METRICS_API_KEY (for Bearer token auth)")
        print("   - JWT_SECRET (for JWT token generation)")
        return False
    
    # Test the configuration
    success = test_authentication(
        username=env_constants.METRICS_AUTH_USERNAME,
        password=env_constants.METRICS_AUTH_PASSWORD,
        api_key=env_constants.METRICS_API_KEY,
        jwt_secret=env_constants.JWT_SECRET
    )
    
    if success:
        print("\n✓ Metrics authentication configuration is valid")
    else:
        print("\n❌ Metrics authentication configuration has issues")
    
    return success


def print_example_config():
    """Print example configuration for metrics authentication."""
    print("Example environment configuration for metrics authentication:")
    print()
    print("# Enable metrics authentication")
    print("export METRICS_AUTH_ENABLED=true")
    print()
    print("# Option 1: Basic Authentication")
    print("export METRICS_AUTH_USERNAME=metrics")
    print("export METRICS_AUTH_PASSWORD=your-secure-password")
    print()
    print("# Option 2: API Key Authentication")
    print("export METRICS_API_KEY=your-api-key")
    print()
    print("# Option 3: JWT Token Authentication")
    print("export JWT_SECRET=your-jwt-secret")
    print()
    print("# Additional security settings")
    print("export METRICS_MAX_FAILED_ATTEMPTS=5")
    print("export METRICS_LOCKOUT_DURATION=300")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Metrics authentication administration tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s generate-api-key
  %(prog)s generate-password --length 20
  %(prog)s create-token --duration 7200 --jwt-secret mysecret
  %(prog)s test-auth --api-key mykey123
  %(prog)s validate-config
  %(prog)s example-config
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Generate API key command
    api_key_parser = subparsers.add_parser('generate-api-key', help='Generate a secure API key')
    api_key_parser.add_argument(
        '--length', 
        type=int, 
        default=32, 
        help='Length in bytes (default: 32)'
    )
    
    # Generate password command
    password_parser = subparsers.add_parser('generate-password', help='Generate a secure password')
    password_parser.add_argument(
        '--length', 
        type=int, 
        default=16, 
        help='Password length (default: 16)'
    )
    
    # Create token command
    token_parser = subparsers.add_parser('create-token', help='Create a JWT token')
    token_parser.add_argument(
        '--duration', 
        type=int, 
        default=3600, 
        help='Token duration in seconds (default: 3600)'
    )
    token_parser.add_argument('--username', help='Basic auth username')
    token_parser.add_argument('--password', help='Basic auth password')
    token_parser.add_argument('--api-key', help='API key')
    token_parser.add_argument('--jwt-secret', help='JWT secret')
    
    # Test authentication command
    test_parser = subparsers.add_parser('test-auth', help='Test authentication configuration')
    test_parser.add_argument('--username', help='Basic auth username')
    test_parser.add_argument('--password', help='Basic auth password')
    test_parser.add_argument('--api-key', help='API key')
    test_parser.add_argument('--jwt-secret', help='JWT secret')
    
    # Validate configuration command
    subparsers.add_parser('validate-config', help='Validate current configuration')
    
    # Example configuration command
    subparsers.add_parser('example-config', help='Show example configuration')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    try:
        if args.command == 'generate-api-key':
            api_key = generate_api_key(args.length)
            print(f"Generated API key: {api_key}")
            print()
            print("Set this as an environment variable:")
            print(f"export METRICS_API_KEY={api_key}")
            
        elif args.command == 'generate-password':
            password = generate_password(args.length)
            print(f"Generated password: {password}")
            print()
            print("Set this as an environment variable:")
            print(f"export METRICS_AUTH_PASSWORD={password}")
            
        elif args.command == 'create-token':
            token = create_jwt_token(
                duration=args.duration,
                username=args.username,
                password=args.password,
                api_key=args.api_key,
                jwt_secret=args.jwt_secret
            )
            print(f"JWT Token: {token}")
            print(f"Expires in: {args.duration} seconds")
            
        elif args.command == 'test-auth':
            success = test_authentication(
                username=args.username,
                password=args.password,
                api_key=args.api_key,
                jwt_secret=args.jwt_secret
            )
            return 0 if success else 1
            
        elif args.command == 'validate-config':
            success = validate_configuration()
            return 0 if success else 1
            
        elif args.command == 'example-config':
            print_example_config()
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())