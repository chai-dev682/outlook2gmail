import os
import logging
import json
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from cryptography.fernet import Fernet
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

logger = logging.getLogger(__name__)

class GmailService:
    """Service for managing multiple Gmail accounts and sending emails"""
    
    def __init__(self, encryption_key=None):
        self.encryption_key = encryption_key or self._get_or_create_encryption_key()
        self.fernet = Fernet(self.encryption_key)
        
        # Gmail OAuth configuration
        self.scopes = [
            'https://www.googleapis.com/auth/gmail.send',
            'https://www.googleapis.com/auth/userinfo.email',
            'https://www.googleapis.com/auth/userinfo.profile'
        ]
        
    def _get_or_create_encryption_key(self):
        """Get or create encryption key for tokens"""
        key_file = 'config/gmail_encryption_key.key'
        
        if os.path.exists(key_file):
            with open(key_file, 'rb') as f:
                return f.read()
        else:
            # Create new key
            key = Fernet.generate_key()
            os.makedirs('config', exist_ok=True)
            with open(key_file, 'wb') as f:
                f.write(key)
            return key
    
    def encrypt_token(self, token):
        """Encrypt a token for storage"""
        if not token:
            return None
        return self.fernet.encrypt(token.encode()).decode()
    
    def decrypt_token(self, encrypted_token):
        """Decrypt a token from storage"""
        if not encrypted_token:
            return None
        return self.fernet.decrypt(encrypted_token.encode()).decode()
    
    def get_oauth_flow(self, credentials_file, redirect_uri):
        """Create OAuth flow for Gmail authentication"""
        try:
            flow = Flow.from_client_secrets_file(
                credentials_file,
                scopes=self.scopes,
                redirect_uri=redirect_uri
            )
            return flow
        except Exception as e:
            logger.error(f"Failed to create OAuth flow: {str(e)}")
            return None
    
    def get_auth_url(self, credentials_file, redirect_uri, state=None):
        """Get authorization URL for Gmail OAuth"""
        flow = self.get_oauth_flow(credentials_file, redirect_uri)
        if not flow:
            return None
            
        auth_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            state=state
        )
        return auth_url
    
    def exchange_code_for_tokens(self, credentials_file, redirect_uri, code):
        """Exchange authorization code for tokens"""
        try:
            flow = self.get_oauth_flow(credentials_file, redirect_uri)
            if not flow:
                return None
                
            flow.fetch_token(code=code)
            credentials = flow.credentials
            
            return {
                'access_token': credentials.token,
                'refresh_token': credentials.refresh_token,
                'expires_in': 3600,  # Default to 1 hour
                'token_uri': credentials.token_uri,
                'client_id': credentials.client_id,
                'client_secret': credentials.client_secret,
                'scopes': credentials.scopes
            }
        except Exception as e:
            logger.error(f"Failed to exchange code for tokens: {str(e)}")
            return None
    
    def refresh_access_token(self, gmail_account):
        """Refresh access token for a Gmail account"""
        try:
            if not gmail_account.refresh_token:
                return None
                
            refresh_token = self.decrypt_token(gmail_account.refresh_token)
            if not refresh_token:
                return None
            
            # Create credentials object
            creds = Credentials(
                token=None,  # Will be refreshed
                refresh_token=refresh_token,
                token_uri='https://oauth2.googleapis.com/token',
                client_id=os.environ.get('GMAIL_CLIENT_ID'),
                client_secret=os.environ.get('GMAIL_CLIENT_SECRET'),
                scopes=self.scopes
            )
            
            # Refresh the token
            creds.refresh(Request())
            
            return {
                'access_token': creds.token,
                'expires_in': 3600,
                'refresh_token': creds.refresh_token or refresh_token
            }
            
        except Exception as e:
            logger.error(f"Failed to refresh access token for {gmail_account.email}: {str(e)}")
            return None
    
    def get_user_info(self, access_token):
        """Get user info from Gmail API"""
        try:
            creds = Credentials(token=access_token)
            service = build('oauth2', 'v2', credentials=creds)
            user_info = service.userinfo().get().execute()
            return user_info
        except Exception as e:
            logger.error(f"Failed to get user info: {str(e)}")
            return None
    
    def create_gmail_service(self, gmail_account):
        """Create Gmail API service for a specific account"""
        try:
            # Get valid access token
            access_token = self.decrypt_token(gmail_account.access_token)
            
            # Check if token needs refresh
            if gmail_account.token_expires_at and gmail_account.token_expires_at <= datetime.utcnow():
                token_result = self.refresh_access_token(gmail_account)
                if token_result:
                    access_token = token_result['access_token']
                    # Update account with new tokens
                    gmail_account.access_token = self.encrypt_token(access_token)
                    gmail_account.token_expires_at = datetime.utcnow() + timedelta(seconds=token_result['expires_in'])
                    if token_result['refresh_token'] != self.decrypt_token(gmail_account.refresh_token):
                        gmail_account.refresh_token = self.encrypt_token(token_result['refresh_token'])
                else:
                    logger.error(f"Failed to refresh token for {gmail_account.email}")
                    return None
            
            # Create credentials
            creds = Credentials(token=access_token)
            
            # Build service
            service = build('gmail', 'v1', credentials=creds)
            return service
            
        except Exception as e:
            logger.error(f"Failed to create Gmail service for {gmail_account.email}: {str(e)}")
            return None
    
    def send_email(self, gmail_account, subject, body, attachments=None, is_html=False):
        """Send email through specific Gmail account"""
        try:
            service = self.create_gmail_service(gmail_account)
            if not service:
                return None
            
            # Create message
            if attachments:
                message = MIMEMultipart()
            else:
                message = MIMEText(body, 'html' if is_html else 'plain')
                message['to'] = gmail_account.email  # Send to self for forwarding
                message['subject'] = subject
                message['from'] = gmail_account.email
            
            if attachments:
                message['to'] = gmail_account.email
                message['subject'] = subject
                message['from'] = gmail_account.email
                
                # Add body
                body_part = MIMEText(body, 'html' if is_html else 'plain')
                message.attach(body_part)
                
                # Add attachments
                for attachment in attachments:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(attachment['content'])
                    encoders.encode_base64(part)
                    part.add_header(
                        'Content-Disposition',
                        f'attachment; filename= {attachment["filename"]}'
                    )
                    message.attach(part)
            
            # Convert to Gmail API format
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
            gmail_message = {'raw': raw_message}
            
            # Send message
            result = service.users().messages().send(
                userId='me',
                body=gmail_message
            ).execute()
            
            logger.info(f"Email sent successfully to {gmail_account.email}: {result.get('id')}")
            return result.get('id')
            
        except HttpError as e:
            logger.error(f"Gmail API error sending to {gmail_account.email}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Failed to send email to {gmail_account.email}: {str(e)}")
            return None
    
    def test_account_connection(self, gmail_account):
        """Test if Gmail account is properly configured and accessible"""
        try:
            service = self.create_gmail_service(gmail_account)
            if not service:
                return False, "Failed to create Gmail service"
            
            # Test by getting user profile
            profile = service.users().getProfile(userId='me').execute()
            if profile:
                return True, f"Connected as {profile.get('emailAddress')}"
            else:
                return False, "Could not retrieve user profile"
                
        except Exception as e:
            return False, str(e)