import msal
import requests
from config.config import Config
from datetime import datetime, timedelta
import logging
from cryptography.fernet import Fernet
import os
import base64
import time

logger = logging.getLogger(__name__)

class MicrosoftAuth:
    """Handle Microsoft OAuth2 authentication and token management"""
    
    def __init__(self, client_id, client_secret, authority=Config.MICROSOFT_AUTHORITY):
        self.client_id = client_id
        self.client_secret = client_secret
        self.authority = authority
        self.scope = ['https://graph.microsoft.com/Mail.Read', 
                     'https://graph.microsoft.com/Mail.Send',
                     'https://graph.microsoft.com/User.Read']
        
        # Initialize encryption key
        self.cipher_suite = self._get_cipher_suite()
        
        # Create MSAL app
        self.app = msal.ConfidentialClientApplication(
            client_id,
            authority=authority,
            client_credential=client_secret
        )
    
    def _get_cipher_suite(self):
        """Get or create encryption key for storing tokens"""
        key_file = 'config/encryption.key'
        if os.path.exists(key_file):
            with open(key_file, 'rb') as f:
                key = f.read()
        else:
            key = Fernet.generate_key()
            os.makedirs('config', exist_ok=True)
            with open(key_file, 'wb') as f:
                f.write(key)
        return Fernet(key)
    
    def encrypt_token(self, token):
        """Encrypt token for storage"""
        if token:
            return self.cipher_suite.encrypt(token.encode()).decode()
        return None
    
    def decrypt_token(self, encrypted_token):
        """Decrypt token from storage"""
        if encrypted_token:
            return self.cipher_suite.decrypt(encrypted_token.encode()).decode()
        return None
    
    def get_auth_url(self, redirect_uri, state=None):
        """Get authorization URL for user consent"""
        auth_url = self.app.get_authorization_request_url(
            self.scope,
            state=state,
            redirect_uri=redirect_uri
        )
        return auth_url
    
    def acquire_token_by_code(self, code, redirect_uri):
        """Exchange authorization code for tokens"""
        try:
            result = self.app.acquire_token_by_authorization_code(
                code,
                scopes=self.scope,
                redirect_uri=redirect_uri
            )
            
            if 'access_token' in result:
                return {
                    'access_token': result['access_token'],
                    'refresh_token': result.get('refresh_token'),
                    'expires_in': result.get('expires_in', 3600)
                }
            else:
                logger.error(f"Token acquisition failed: {result.get('error_description')}")
                return None
                
        except Exception as e:
            logger.error(f"Error acquiring token by code: {str(e)}")
            return None
    
    def refresh_access_token(self, refresh_token):
        """Get new access token using refresh token"""
        try:
            result = self.app.acquire_token_by_refresh_token(
                refresh_token=refresh_token,
                scopes=self.scope
            )
            
            if 'access_token' in result:
                return {
                    'access_token': result['access_token'],
                    'refresh_token': result.get('refresh_token', refresh_token),
                    'expires_in': result.get('expires_in', 3600)
                }
            
            # Check if the error is due to token from different application
            error_codes = result.get('error_codes', [])
            if 70000 in error_codes or result.get('error') == 'invalid_grant':
                logger.error(f"Refresh token was issued for a different application. User needs to re-authenticate.")
                return {
                    'error': 'different_client_id', 
                    'message': 'This refresh token was issued for a different application (likely AYCD). Please re-authenticate with this application.',
                    'requires_reauth': True
                }
            
            # If MSAL fails for other reasons, log the error and try direct endpoint
            logger.warning(f"MSAL token refresh failed: {result.get('error_description', 'Unknown error')}")
                    
        except Exception as e:
            logger.error(f"Error refreshing token: {str(e)}")
            return {'error': 'unexpected_error', 'message': f"Unexpected error: {str(e)}"}
    
    def validate_token(self, access_token):
        """Validate if access token is still valid"""
        try:
            headers = {'Authorization': f'Bearer {access_token}'}
            response = requests.get('https://graph.microsoft.com/v1.0/me', headers=headers)
            return response.status_code == 200
        except:
            return False
    
    def get_user_info(self, access_token):
        """Get user information from Microsoft Graph"""
        try:
            headers = {'Authorization': f'Bearer {access_token}'}
            response = requests.get('https://graph.microsoft.com/v1.0/me', headers=headers)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get user info: {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting user info: {str(e)}")
            return None
    
    def extract_proxy_info(self, proxy_string):
        """Extract proxy information from CSV format"""
        # Format: host:port:username:password
        if not proxy_string:
            return None
            
        parts = proxy_string.split(':')
        if len(parts) >= 2:
            return {
                'host': parts[0],
                'port': int(parts[1]),
                'username': parts[2] if len(parts) > 2 else None,
                'password': parts[3] if len(parts) > 3 else None
            }
        return None 