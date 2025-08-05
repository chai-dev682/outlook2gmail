import base64
import logging
import requests
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import html2text
from bs4 import BeautifulSoup
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import json
import time
from tqdm import tqdm

logger = logging.getLogger(__name__)

class EmailForwarder:
    """Service for forwarding emails from Outlook to Gmail"""
    
    def __init__(self, microsoft_auth, gmail_creds_file, gmail_target_email):
        self.microsoft_auth = microsoft_auth
        self.gmail_creds_file = gmail_creds_file
        self.gmail_target_email = gmail_target_email
        self.gmail_service = None
        self.h2t = html2text.HTML2Text()
        self.h2t.ignore_links = False
        
    def initialize_gmail_service(self):
        """Initialize Gmail API service"""
        try:
            creds = Credentials.from_authorized_user_file(self.gmail_creds_file)
            self.gmail_service = build('gmail', 'v1', credentials=creds)
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Gmail service: {str(e)}")
            return False
    
    def get_outlook_emails(self, access_token, account, max_emails=100, last_sync_date=None):
        """Fetch emails from Outlook using Microsoft Graph API"""
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json'
        }
        
        # Build query parameters
        params = {
            '$orderby': 'receivedDateTime desc',
            '$top': min(max_emails, 100),  # Graph API max is 100 per request
            '$select': 'id,subject,from,receivedDateTime,bodyPreview,hasAttachments,body'
        }
        
        # Add date filter if last sync date is provided
        if last_sync_date:
            filter_date = last_sync_date.strftime('%Y-%m-%dT%H:%M:%SZ')
            params['$filter'] = f'receivedDateTime gt {filter_date}'
        
        # Handle proxy if configured
        proxies = None
        if account.proxy_host and account.proxy_port:
            proxy_url = f"http://{account.proxy_host}:{account.proxy_port}"
            if account.proxy_username and account.proxy_password:
                proxy_url = f"http://{account.proxy_username}:{account.proxy_password}@{account.proxy_host}:{account.proxy_port}"
            proxies = {'http': proxy_url, 'https': proxy_url}
        
        emails = []
        url = 'https://graph.microsoft.com/v1.0/me/messages'
        
        try:
            while url and len(emails) < max_emails:
                response = requests.get(url, headers=headers, params=params if not emails else None, proxies=proxies)
                
                if response.status_code == 200:
                    data = response.json()
                    emails.extend(data.get('value', []))
                    url = data.get('@odata.nextLink')  # Get next page URL
                    
                    # Break if we have enough emails
                    if len(emails) >= max_emails:
                        emails = emails[:max_emails]
                        break
                else:
                    logger.error(f"Failed to fetch emails for {account.username}: {response.text}")
                    break
                    
            return emails
            
        except Exception as e:
            logger.error(f"Error fetching emails for {account.username}: {str(e)}")
            return []
    
    def get_email_attachments(self, access_token, message_id, proxies=None):
        """Fetch attachments for a specific email"""
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json'
        }
        
        url = f'https://graph.microsoft.com/v1.0/me/messages/{message_id}/attachments'
        
        try:
            response = requests.get(url, headers=headers, proxies=proxies)
            
            if response.status_code == 200:
                data = response.json()
                return data.get('value', [])
            else:
                logger.error(f"Failed to fetch attachments: {response.text}")
                return []
                
        except Exception as e:
            logger.error(f"Error fetching attachments: {str(e)}")
            return []
    
    def create_forward_message(self, outlook_email, attachments=None):
        """Create a MIME message for forwarding"""
        message = MIMEMultipart()
        
        # Set headers
        from_info = outlook_email.get('from', {})
        sender_name = from_info.get('emailAddress', {}).get('name', 'Unknown')
        sender_email = from_info.get('emailAddress', {}).get('address', 'unknown@outlook.com')
        
        message['To'] = self.gmail_target_email
        message['Subject'] = f"FWD: {outlook_email.get('subject', 'No Subject')}"
        
        # Create forward header
        received_date = outlook_email.get('receivedDateTime', '')
        forward_header = f"""
---------- Forwarded message ----------
From: {sender_name} <{sender_email}>
Date: {received_date}
Subject: {outlook_email.get('subject', 'No Subject')}

"""
        
        # Get email body
        body_content = outlook_email.get('body', {}).get('content', '')
        body_type = outlook_email.get('body', {}).get('contentType', 'text')
        
        # Convert HTML to text if needed
        if body_type.lower() == 'html':
            text_body = self.h2t.handle(body_content)
            full_body = forward_header + text_body
            
            # Attach both text and HTML versions
            message.attach(MIMEText(full_body, 'plain'))
            message.attach(MIMEText(forward_header + body_content, 'html'))
        else:
            full_body = forward_header + body_content
            message.attach(MIMEText(full_body, 'plain'))
        
        # Add attachments if any
        if attachments:
            for attachment in attachments:
                self._add_attachment(message, attachment)
        
        return message
    
    def _add_attachment(self, message, attachment):
        """Add attachment to MIME message"""
        try:
            # Get attachment data
            content = attachment.get('contentBytes', '')
            filename = attachment.get('name', 'attachment')
            content_type = attachment.get('contentType', 'application/octet-stream')
            
            # Decode base64 content
            file_data = base64.b64decode(content)
            
            # Create MIME attachment
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(file_data)
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
            
            message.attach(part)
            
        except Exception as e:
            logger.error(f"Error adding attachment: {str(e)}")
    
    def send_to_gmail(self, message):
        """Send message using Gmail API"""
        try:
            # Convert message to base64
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            body = {'raw': raw_message}
            
            # Send message
            result = self.gmail_service.users().messages().send(
                userId='me',
                body=body
            ).execute()
            
            return result.get('id')
            
        except HttpError as e:
            logger.error(f"Gmail API error: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error sending to Gmail: {str(e)}")
            return None
    
    def forward_emails(self, account, db, max_emails=1000):
        """Forward emails from an Outlook account to Gmail"""
        from .models import ForwardingHistory
        
        # Check if account has valid tokens
        if not account.refresh_token:
            logger.error(f"No refresh token for account {account.username}")
            return {'success': 0, 'failed': 0, 'errors': ['No refresh token']}
        
        # Decrypt and refresh access token
        refresh_token = self.microsoft_auth.decrypt_token(account.refresh_token)
        token_result = self.microsoft_auth.refresh_access_token(refresh_token)
        
        if not token_result or 'error' in token_result:
            error_msg = "Failed to refresh access token"
            if token_result and 'message' in token_result:
                error_msg = token_result['message']
                
            logger.error(f"Failed to refresh token for {account.username}: {error_msg}")
            account.last_error = error_msg
            account.consecutive_errors += 1
            
            # If it's an invalid token error, deactivate the account
            if token_result and token_result.get('error') == 'invalid_token':
                account.is_active = False
                logger.warning(f"Deactivating account {account.username} due to invalid refresh token")
                
            db.session.commit()
            return {'success': 0, 'failed': 0, 'errors': [error_msg]}
        
        # Update access token
        access_token = token_result['access_token']
        account.access_token = self.microsoft_auth.encrypt_token(access_token)
        account.token_expires_at = datetime.utcnow() + timedelta(seconds=token_result['expires_in'])
        
        # Update refresh token if a new one was provided
        if token_result.get('refresh_token') and token_result['refresh_token'] != refresh_token:
            account.refresh_token = self.microsoft_auth.encrypt_token(token_result['refresh_token'])
            logger.info(f"Updated refresh token for {account.username}")
        
        # Get emails
        emails = self.get_outlook_emails(access_token, account, max_emails, account.last_sync)
        
        if not emails:
            logger.info(f"No new emails for {account.username}")
            account.last_sync = datetime.utcnow()
            account.consecutive_errors = 0
            db.session.commit()
            return {'success': 0, 'failed': 0, 'errors': []}
        
        # Forward emails
        success_count = 0
        failed_count = 0
        errors = []
        
        # Setup proxy for attachments if needed
        proxies = None
        if account.proxy_host and account.proxy_port:
            proxy_url = f"http://{account.proxy_host}:{account.proxy_port}"
            if account.proxy_username and account.proxy_password:
                proxy_url = f"http://{account.proxy_username}:{account.proxy_password}@{account.proxy_host}:{account.proxy_port}"
            proxies = {'http': proxy_url, 'https': proxy_url}
        
        for email in tqdm(emails, desc=f"Forwarding emails for {account.username}"):
            try:
                # Check if already forwarded
                existing = ForwardingHistory.query.filter_by(
                    account_id=account.id,
                    outlook_message_id=email['id']
                ).first()
                
                if existing and existing.status == 'success':
                    continue
                
                # Get attachments if any
                attachments = None
                if email.get('hasAttachments', False):
                    attachments = self.get_email_attachments(access_token, email['id'], proxies)
                
                # Create forward message
                forward_msg = self.create_forward_message(email, attachments)
                
                # Send to Gmail
                gmail_id = self.send_to_gmail(forward_msg)
                
                if gmail_id:
                    # Record success
                    if existing:
                        existing.status = 'success'
                        existing.gmail_message_id = gmail_id
                        existing.forwarded_at = datetime.utcnow()
                    else:
                        history = ForwardingHistory(
                            account_id=account.id,
                            outlook_message_id=email['id'],
                            subject=email.get('subject', ''),
                            sender=email.get('from', {}).get('emailAddress', {}).get('address', ''),
                            received_date=datetime.fromisoformat(email.get('receivedDateTime', '').replace('Z', '+00:00')),
                            gmail_message_id=gmail_id,
                            status='success',
                            has_attachments=email.get('hasAttachments', False)
                        )
                        db.session.add(history)
                    
                    success_count += 1
                else:
                    # Record failure
                    if existing:
                        existing.status = 'failed'
                        existing.retry_count += 1
                        existing.error_message = 'Failed to send to Gmail'
                    else:
                        history = ForwardingHistory(
                            account_id=account.id,
                            outlook_message_id=email['id'],
                            subject=email.get('subject', ''),
                            sender=email.get('from', {}).get('emailAddress', {}).get('address', ''),
                            received_date=datetime.fromisoformat(email.get('receivedDateTime', '').replace('Z', '+00:00')),
                            status='failed',
                            error_message='Failed to send to Gmail',
                            has_attachments=email.get('hasAttachments', False)
                        )
                        db.session.add(history)
                    
                    failed_count += 1
                    errors.append(f"Failed to forward: {email.get('subject', 'No subject')}")
                
                # Commit periodically
                if (success_count + failed_count) % 10 == 0:
                    db.session.commit()
                
                # Rate limiting
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Error forwarding email {email.get('id')}: {str(e)}")
                failed_count += 1
                errors.append(str(e))
        
        # Update account statistics
        account.total_emails_forwarded += success_count
        account.total_emails_failed += failed_count
        account.last_sync = datetime.utcnow()
        account.consecutive_errors = 0 if success_count > 0 else account.consecutive_errors + 1
        
        if errors:
            account.last_error = '; '.join(errors[:5])  # Store first 5 errors
        else:
            account.last_error = None
        
        db.session.commit()
        
        return {
            'success': success_count,
            'failed': failed_count,
            'errors': errors
        } 