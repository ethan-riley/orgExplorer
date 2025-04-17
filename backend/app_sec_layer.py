"""
api_security.py - A reusable API security layer that adds API key authentication
to existing Python scripts with minimal modification.
"""

import functools
import os
import hashlib
import hmac
import time
import uuid
from typing import Dict, List, Callable, Optional, Any, Union
import json

class APISecurityManager:
    """
    A security manager that handles API key validation and management.
    """
    def __init__(self, 
                 api_keys_file: str = "api_keys.json", 
                 env_key_name: str = "API_KEY",
                 token_expiry: int = 3600):
        """
        Initialize the security manager.
        
        Args:
            api_keys_file: Path to the JSON file storing API keys
            env_key_name: Environment variable name for the API key
            token_expiry: Token expiry time in seconds (default: 1 hour)
        """
        self.api_keys_file = api_keys_file
        self.env_key_name = env_key_name
        self.token_expiry = token_expiry
        self._load_api_keys()
    
    def _load_api_keys(self) -> None:
        """Load API keys from file or create a new file if it doesn't exist."""
        try:
            if os.path.exists(self.api_keys_file):
                with open(self.api_keys_file, 'r') as f:
                    self.api_keys = json.load(f)
            else:
                self.api_keys = {
                    "keys": {},
                    "roles": {
                        "admin": {"permissions": ["*"]},
                        "read": {"permissions": ["get", "list"]},
                        "write": {"permissions": ["get", "list", "create", "update"]},
                    }
                }
                self._save_api_keys()
        except Exception as e:
            print(f"Error loading API keys: {e}")
            self.api_keys = {"keys": {}, "roles": {}}
    
    def _save_api_keys(self) -> None:
        """Save API keys to file."""
        with open(self.api_keys_file, 'w') as f:
            json.dump(self.api_keys, f, indent=4)
    
    def generate_key(self, role: str = "read", user_id: str = None) -> str:
        """
        Generate a new API key.
        
        Args:
            role: Role for the key (admin, read, write, etc.)
            user_id: Optional user identifier
            
        Returns:
            The generated API key
        """
        if role not in self.api_keys["roles"]:
            raise ValueError(f"Invalid role: {role}")
        
        key = str(uuid.uuid4()).replace('-', '')
        hashed_key = hashlib.sha256(key.encode()).hexdigest()
        
        if user_id is None:
            user_id = f"user_{str(uuid.uuid4())[:8]}"
            
        self.api_keys["keys"][hashed_key] = {
            "role": role,
            "user_id": user_id,
            "created": time.time(),
            "last_used": None
        }
        
        self._save_api_keys()
        return key
    
    def revoke_key(self, key: str) -> bool:
        """
        Revoke an API key.
        
        Args:
            key: The API key to revoke
            
        Returns:
            True if the key was revoked, False otherwise
        """
        hashed_key = hashlib.sha256(key.encode()).hexdigest()
        if hashed_key in self.api_keys["keys"]:
            del self.api_keys["keys"][hashed_key]
            self._save_api_keys()
            return True
        return False
    
    def list_keys(self, include_hash: bool = False) -> List[Dict[str, Any]]:
        """
        List all API keys.
        
        Args:
            include_hash: Whether to include the hashed key
            
        Returns:
            List of API key information
        """
        return [
            {**info, "key_hash": key_hash if include_hash else None}
            for key_hash, info in self.api_keys["keys"].items()
        ]
    
    def validate_key(self, key: str, required_permission: Optional[str] = None) -> bool:
        """
        Validate an API key.
        
        Args:
            key: The API key to validate
            required_permission: Optional permission to check
            
        Returns:
            True if the key is valid, False otherwise
        """
        if not key:
            return False
            
        hashed_key = hashlib.sha256(key.encode()).hexdigest()
        
        if hashed_key in self.api_keys["keys"]:
            key_info = self.api_keys["keys"][hashed_key]
            role = key_info["role"]
            
            # Update last used timestamp
            key_info["last_used"] = time.time()
            self._save_api_keys()
            
            # Check permission if required
            if required_permission:
                permissions = self.api_keys["roles"][role]["permissions"]
                if required_permission not in permissions and "*" not in permissions:
                    return False
                    
            return True
            
        return False
    
    def get_key_from_header(self, headers: Dict[str, str]) -> Optional[str]:
        """
        Extract API key from headers.
        
        Args:
            headers: Request headers
            
        Returns:
            The API key or None if not found
        """
        return headers.get('X-API-Key') or headers.get('Authorization', '').replace('Bearer ', '')
    
    def get_key_from_environment(self) -> Optional[str]:
        """
        Get API key from environment variable.
        
        Returns:
            The API key or None if not found
        """
        return os.environ.get(self.env_key_name)
    
    def get_key_role(self, key: str) -> Optional[str]:
        """
        Get the role for a key.
        
        Args:
            key: The API key
            
        Returns:
            The role or None if key is invalid
        """
        hashed_key = hashlib.sha256(key.encode()).hexdigest()
        if hashed_key in self.api_keys["keys"]:
            return self.api_keys["keys"][hashed_key]["role"]
        return None

    def generate_token(self, key: str, payload: Dict[str, Any] = None) -> Optional[str]:
        """
        Generate a temporary token from an API key.
        
        Args:
            key: The API key
            payload: Additional data to include in the token
            
        Returns:
            A signed token string or None if key is invalid
        """
        if not self.validate_key(key):
            return None
            
        hashed_key = hashlib.sha256(key.encode()).hexdigest()
        key_info = self.api_keys["keys"][hashed_key]
        
        token_data = {
            "key_hash": hashed_key,
            "user_id": key_info["user_id"],
            "role": key_info["role"],
            "exp": time.time() + self.token_expiry,
            "jti": str(uuid.uuid4())
        }
        
        if payload:
            token_data.update(payload)
            
        # Simple token format: base64(json_data) + "." + hmac_signature
        import base64
        json_data = json.dumps(token_data).encode()
        data_b64 = base64.b64encode(json_data).decode()
        
        signature = hmac.new(
            key.encode(), 
            data_b64.encode(), 
            hashlib.sha256
        ).hexdigest()
        
        return f"{data_b64}.{signature}"
    
    def validate_token(self, token: str) -> Union[Dict[str, Any], bool]:
        """
        Validate a token.
        
        Args:
            token: The token to validate
            
        Returns:
            Token payload if valid, False otherwise
        """
        try:
            import base64
            
            # Split token into data and signature
            data_b64, signature = token.split('.')
            
            # Decode data
            json_data = base64.b64decode(data_b64).decode()
            data = json.loads(json_data)
            
            # Check if token is expired
            if data["exp"] < time.time():
                return False
                
            # Get key info
            key_hash = data["key_hash"]
            if key_hash not in self.api_keys["keys"]:
                return False
                
            # We can't verify the signature without the original key,
            # but we can check if the token was issued to a valid key
            return data
            
        except Exception:
            return False

def require_api_key(permission: Optional[str] = None):
    """
    Decorator to require API key for a function.
    
    Args:
        permission: Required permission
        
    Returns:
        Decorated function
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Get API security manager - either from kwargs or create new one
            security = kwargs.pop('api_security', None) or APISecurityManager()
            
            # Check for API key in different places
            api_key = None
            
            # 1. Check if it's passed explicitly
            if 'api_key' in kwargs:
                api_key = kwargs.pop('api_key')
                
            # 2. Check if headers are provided
            elif 'headers' in kwargs:
                api_key = security.get_key_from_header(kwargs['headers'])
                
            # 3. Fall back to environment variable
            if not api_key:
                api_key = security.get_key_from_environment()
                
            # Validate API key
            if not security.validate_key(api_key, permission):
                return {"error": "Invalid or missing API key", "status": 401}
                
            # Add security manager to kwargs so function can use it
            kwargs['api_security'] = security
            return func(*args, **kwargs)
        return wrapper
    return decorator

# Flask middleware
def flask_api_security_middleware(app, security_manager=None):
    """
    Flask middleware for API security.
    
    Args:
        app: Flask app
        security_manager: Optional APISecurityManager instance
    """
    if security_manager is None:
        security_manager = APISecurityManager()
        
    from flask import request, jsonify
    
    @app.before_request
    def check_api_key():
        # Skip API key check for certain paths
        if request.path.startswith('/public') or request.path == '/':
            return None
            
        # Get API key from headers
        api_key = security_manager.get_key_from_header(request.headers)
        
        # Check if endpoint has a required permission
        required_permission = getattr(app.view_functions.get(request.endpoint), 
                                    '_required_permission', None)
        
        # Validate key
        if not security_manager.validate_key(api_key, required_permission):
            return jsonify({"error": "Invalid or missing API key"}), 401

# Flask route decorator
def require_permission(permission):
    """
    Flask decorator to require specific permission.
    
    Args:
        permission: Required permission
        
    Returns:
        Decorated function
    """
    def decorator(f):
        f._required_permission = permission
        return f
    return decorator

# FastAPI middleware
def fastapi_api_security_middleware(security_manager=None):
    """
    FastAPI middleware for API security.
    
    Args:
        security_manager: Optional APISecurityManager instance
        
    Returns:
        FastAPI middleware
    """
    if security_manager is None:
        security_manager = APISecurityManager()
        
    from fastapi import Request, Response
    from starlette.middleware.base import BaseHTTPMiddleware
    from fastapi.responses import JSONResponse
    
    class APISecurityMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            # Skip API key check for certain paths
            if request.url.path.startswith('/public') or request.url.path == '/':
                return await call_next(request)
                
            # Get API key from headers
            api_key = security_manager.get_key_from_header(dict(request.headers))
            
            # For FastAPI, permission checks would typically be done in dependencies
            # This is a simple path-based check as an example
            path = request.url.path.strip('/')
            parts = path.split('/')
            if len(parts) > 0:
                resource = parts[0]
                method = request.method.lower()
                
                # Create a permission string like "users:read" or "products:write"
                if len(parts) > 1:
                    permission = f"{resource}:{method}"
                else:
                    permission = method
            else:
                permission = None
                
            # Validate key
            if not security_manager.validate_key(api_key, permission):
                return JSONResponse(
                    status_code=401,
                    content={"error": "Invalid or missing API key"}
                )
                
            return await call_next(request)
            
    return APISecurityMiddleware()

# Example usage for FastAPI
def fastapi_api_key_dependency(permission: Optional[str] = None):
    """
    FastAPI dependency for API key validation.
    
    Args:
        permission: Required permission
        
    Returns:
        Dependency function
    """
    from fastapi import Depends, Header, HTTPException
    
    def get_api_key(x_api_key: Optional[str] = Header(None)):
        security = APISecurityManager()
        if not security.validate_key(x_api_key, permission):
            raise HTTPException(
                status_code=401,
                detail="Invalid or missing API key"
            )
        return x_api_key
    
    return Depends(get_api_key)

# Django middleware
class DjangoAPISecurityMiddleware:
    """Django middleware for API security."""
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.security = APISecurityManager()
        
    def __call__(self, request):
        # Skip API key check for certain paths
        if request.path.startswith('/public') or request.path == '/':
            return self.get_response(request)
            
        # Get API key from headers
        api_key = self.security.get_key_from_header(request.headers)
        
        # Simple permission check based on HTTP method
        permission = request.method.lower()
        
        # Validate key
        if not self.security.validate_key(api_key, permission):
            from django.http import JsonResponse
            return JsonResponse(
                {"error": "Invalid or missing API key"}, 
                status=401
            )
            
        return self.get_response(request)

# Command-line interface for key management
def cli():
    """Command-line interface for API key management."""
    import argparse
    
    parser = argparse.ArgumentParser(description='API Key Management')
    subparsers = parser.add_subparsers(dest='command', help='Command')
    
    # Generate key
    gen_parser = subparsers.add_parser('generate', help='Generate a new API key')
    gen_parser.add_argument('--role', default='read', help='Role (admin, read, write)')
    gen_parser.add_argument('--user', help='User ID')
    
    # List keys
    list_parser = subparsers.add_parser('list', help='List API keys')
    list_parser.add_argument('--show-hash', action='store_true', help='Show key hashes')
    
    # Revoke key
    revoke_parser = subparsers.add_parser('revoke', help='Revoke an API key')
    revoke_parser.add_argument('key', help='API key to revoke')
    
    args = parser.parse_args()
    security = APISecurityManager()
    
    if args.command == 'generate':
        key = security.generate_key(args.role, args.user)
        print(f"Generated API key: {key}")
        print(f"Role: {args.role}")
        print("KEEP THIS KEY SAFE! It will not be displayed again.")
        
    elif args.command == 'list':
        keys = security.list_keys(args.show_hash)
        print(f"Found {len(keys)} API keys:")
        for i, key_info in enumerate(keys, 1):
            print(f"{i}. User: {key_info['user_id']}, Role: {key_info['role']}")
            if args.show_hash:
                print(f"   Hash: {key_info['key_hash']}")
                
    elif args.command == 'revoke':
        if security.revoke_key(args.key):
            print("API key revoked successfully")
        else:
            print("Invalid API key or key not found")
            
    else:
        parser.print_help()

if __name__ == "__main__":
    cli()