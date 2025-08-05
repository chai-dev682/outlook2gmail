import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from src.microsoft_auth import MicrosoftAuth
import msal
import requests

class TestMicrosoftAuth:
    """Test cases for Microsoft authentication"""
    
    @pytest.fixture
    def auth(self):
        """Create MicrosoftAuth instance for testing"""
        return MicrosoftAuth(
            client_id='test-client-id',
            client_secret='test-client-secret'
        )
    
    def test_initialization(self, auth):
        """Test proper initialization of MicrosoftAuth"""
        assert auth.client_id == 'test-client-id'
        assert auth.client_secret == 'test-client-secret'
        assert auth.authority == 'https://login.microsoftonline.com/common'
        assert 'offline_access' in auth.scope
    
    def test_encrypt_decrypt_token(self, auth):
        """Test token encryption and decryption"""
        original_token = 'test-refresh-token-12345'
        
        # Encrypt token
        encrypted = auth.encrypt_token(original_token)
        assert encrypted != original_token
        assert encrypted is not None
        
        # Decrypt token
        decrypted = auth.decrypt_token(encrypted)
        assert decrypted == original_token
    
    def test_encrypt_decrypt_none(self, auth):
        """Test encryption/decryption with None values"""
        assert auth.encrypt_token(None) is None
        assert auth.decrypt_token(None) is None
    
    @patch('msal.ConfidentialClientApplication.get_authorization_request_url')
    def test_get_auth_url(self, mock_get_url, auth):
        """Test getting authorization URL"""
        mock_get_url.return_value = 'https://login.microsoftonline.com/auth'
        
        url = auth.get_auth_url('http://localhost/callback', 'test-state')
        
        assert url == 'https://login.microsoftonline.com/auth'
        mock_get_url.assert_called_once()
    
    @patch('msal.ConfidentialClientApplication.acquire_token_by_authorization_code')
    def test_acquire_token_by_code_success(self, mock_acquire, auth):
        """Test successful token acquisition by code"""
        mock_acquire.return_value = {
            'access_token': 'test-access-token',
            'refresh_token': 'test-refresh-token',
            'expires_in': 3600
        }
        
        result = auth.acquire_token_by_code('test-code', 'http://localhost/callback')
        
        assert result is not None
        assert result['access_token'] == 'test-access-token'
        assert result['refresh_token'] == 'test-refresh-token'
        assert result['expires_in'] == 3600
    
    @patch('msal.ConfidentialClientApplication.acquire_token_by_authorization_code')
    def test_acquire_token_by_code_failure(self, mock_acquire, auth):
        """Test failed token acquisition by code"""
        mock_acquire.return_value = {
            'error': 'invalid_grant',
            'error_description': 'Invalid authorization code'
        }
        
        result = auth.acquire_token_by_code('invalid-code', 'http://localhost/callback')
        
        assert result is None
    
    @patch('requests.post')
    def test_refresh_access_token_success(self, mock_post, auth):
        """Test successful token refresh"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'access_token': 'new-access-token',
            'refresh_token': 'new-refresh-token',
            'expires_in': 3600
        }
        mock_post.return_value = mock_response
        
        result = auth.refresh_access_token('old-refresh-token')
        
        assert result is not None
        assert result['access_token'] == 'new-access-token'
        assert result['refresh_token'] == 'new-refresh-token'
        assert result['expires_in'] == 3600
    
    @patch('requests.post')
    def test_refresh_access_token_failure(self, mock_post, auth):
        """Test failed token refresh"""
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = 'Invalid refresh token'
        mock_post.return_value = mock_response
        
        result = auth.refresh_access_token('invalid-refresh-token')
        
        assert result is None
    
    @patch('requests.get')
    def test_validate_token_valid(self, mock_get, auth):
        """Test token validation with valid token"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        
        is_valid = auth.validate_token('valid-access-token')
        
        assert is_valid is True
        mock_get.assert_called_with(
            'https://graph.microsoft.com/v1.0/me',
            headers={'Authorization': 'Bearer valid-access-token'}
        )
    
    @patch('requests.get')
    def test_validate_token_invalid(self, mock_get, auth):
        """Test token validation with invalid token"""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response
        
        is_valid = auth.validate_token('invalid-access-token')
        
        assert is_valid is False
    
    @patch('requests.get')
    def test_get_user_info_success(self, mock_get, auth):
        """Test getting user info with valid token"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'displayName': 'Test User',
            'mail': 'test@outlook.com',
            'id': 'user-id-123'
        }
        mock_get.return_value = mock_response
        
        user_info = auth.get_user_info('valid-access-token')
        
        assert user_info is not None
        assert user_info['displayName'] == 'Test User'
        assert user_info['mail'] == 'test@outlook.com'
    
    @patch('requests.get')
    def test_get_user_info_failure(self, mock_get, auth):
        """Test getting user info with invalid token"""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = 'Unauthorized'
        mock_get.return_value = mock_response
        
        user_info = auth.get_user_info('invalid-access-token')
        
        assert user_info is None
    
    def test_extract_proxy_info_full(self, auth):
        """Test extracting complete proxy information"""
        proxy_string = '192.168.1.1:8080:username:password'
        
        proxy_info = auth.extract_proxy_info(proxy_string)
        
        assert proxy_info is not None
        assert proxy_info['host'] == '192.168.1.1'
        assert proxy_info['port'] == 8080
        assert proxy_info['username'] == 'username'
        assert proxy_info['password'] == 'password'
    
    def test_extract_proxy_info_minimal(self, auth):
        """Test extracting minimal proxy information"""
        proxy_string = '192.168.1.1:8080'
        
        proxy_info = auth.extract_proxy_info(proxy_string)
        
        assert proxy_info is not None
        assert proxy_info['host'] == '192.168.1.1'
        assert proxy_info['port'] == 8080
        assert proxy_info['username'] is None
        assert proxy_info['password'] is None
    
    def test_extract_proxy_info_invalid(self, auth):
        """Test extracting proxy info from invalid string"""
        assert auth.extract_proxy_info('') is None
        assert auth.extract_proxy_info('invalid') is None
        assert auth.extract_proxy_info('192.168.1.1') is None 