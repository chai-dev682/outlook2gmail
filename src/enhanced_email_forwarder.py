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
import json
import time
from tqdm import tqdm
from .gmail_service import GmailService
from .forwarding_rule_engine import ForwardingRuleEngine
from .models import ForwardingHistory, ForwardingRule, GmailAccount

logger = logging.getLogger(__name__)

class EnhancedEmailForwarder:
    """Enhanced service for forwarding emails from Outlook to specific Gmail accounts based on rules"""
    
    def __init__(self, microsoft_auth):
        self.microsoft_auth = microsoft_auth
        self.gmail_service = GmailService()
        self.rule_engine = ForwardingRuleEngine()
        self.h2t = html2text.HTML2Text()
        self.h2t.ignore_links = True
        self.h2t.ignore_images = True
        
    def get_outlook_emails(self, access_token, account, max_emails=100, last_sync_date=None):
        """Get emails from Outlook account using Microsoft Graph API"""
        try:
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            # Build query
            url = 'https://graph.microsoft.com/v1.0/me/messages'
            params = {
                '$top': min(max_emails, 1000),
                '$orderby': 'receivedDateTime desc',
                '$select': 'id,subject,from,receivedDateTime,hasAttachments,importance,body,toRecipients,ccRecipients,categories,bodyPreview'
            }
            
            # Add date filter if provided
            if last_sync_date:
                # Format date properly for Microsoft Graph API (must include timezone)
                if last_sync_date.tzinfo is None:
                    # If no timezone info, assume UTC and format properly
                    # Microsoft Graph expects: yyyy-mm-ddThh:mm:ss.sssZ
                    date_filter = f"receivedDateTime gt {last_sync_date.strftime('%Y-%m-%dT%H:%M:%S')}.000Z"
                else:
                    # If timezone info exists, use isoformat
                    date_filter = f"receivedDateTime gt {last_sync_date.isoformat()}"
                params['$filter'] = date_filter
                logger.debug(f"Using date filter: {date_filter}")
            
            logger.debug(f"Making request to Microsoft Graph API for {account.email}")
            response = requests.get(url, headers=headers, params=params)
            
            # Reset the 401 flag
            self._last_request_was_401 = False
            
            # Check response status first
            if response.status_code == 200:
                try:
                    data = response.json()
                    emails = data.get('value', [])
                    logger.info(f"Retrieved {len(emails)} emails for {account.email}")
                    return emails
                except ValueError as json_error:
                    logger.error(f"Failed to parse JSON response for {account.email}: {str(json_error)}")
                    logger.error(f"Response content: {response.text[:500]}...")
                    return []
            else:
                logger.error(f"Failed to get emails for {account.email}: {response.status_code} - {response.text}")
                
                # Handle specific error cases
                if response.status_code == 401:
                    self._last_request_was_401 = True  # Track 401 error for retry logic
                    logger.error(f"Access token expired or invalid for {account.email}")
                    logger.error(f"Please re-authenticate the account via the web interface")
                    logger.error(f"Or use CLI: python cli.py reauth {getattr(account, 'id', 'ACCOUNT_ID')}")
                    # Mark account as needing re-authentication
                    if hasattr(account, 'consecutive_errors'):
                        account.consecutive_errors += 1
                elif response.status_code == 403:
                    logger.error(f"Insufficient permissions for {account.email}. Check Microsoft Graph API permissions.")
                elif response.status_code == 429:
                    logger.error(f"Rate limit exceeded for {account.email}. Please wait before trying again.")
                
                return []
                
        except requests.exceptions.RequestException as req_error:
            logger.error(f"Network error getting emails for {account.email if account else 'Unknown'}: {str(req_error)}")
            return []
        except Exception as e:
            logger.error(f"Error getting emails for {account.email if account else 'Unknown'}: {str(e)}")
            return []
    
    def _get_emails_with_retry(self, access_token, account, max_emails, db):
        """Get emails with automatic retry on 401 errors"""
        try:
            # First attempt
            emails = self.get_outlook_emails(access_token, account, max_emails, account.last_sync)
            
            # If we got emails or the error wasn't 401, return the result
            if emails or not hasattr(self, '_last_request_was_401'):
                return emails
            
            # If we got a 401 error, try refreshing the token and retry once
            logger.info(f"Got 401 error for {account.email}, attempting token refresh and retry")
            
            if account.refresh_token:
                refresh_token = self.microsoft_auth.decrypt_token(account.refresh_token)
                token_result = self.microsoft_auth.refresh_access_token(refresh_token)
                
                if token_result and 'error' not in token_result:
                    # Update token
                    account.access_token = self.microsoft_auth.encrypt_token(token_result['access_token'])
                    account.token_expires_at = datetime.utcnow() + timedelta(seconds=token_result['expires_in'])
                    
                    if token_result.get('refresh_token') and token_result['refresh_token'] != refresh_token:
                        account.refresh_token = self.microsoft_auth.encrypt_token(token_result['refresh_token'])
                    
                    db.session.commit()
                    logger.info(f"Token refreshed for {account.email}, retrying API call")
                    
                    # Retry with new token
                    new_access_token = self.microsoft_auth.decrypt_token(account.access_token)
                    return self.get_outlook_emails(new_access_token, account, max_emails, account.last_sync)
                else:
                    logger.error(f"Failed to refresh token for {account.email} during retry")
                    return []
            else:
                logger.error(f"No refresh token available for {account.email} during retry")
                return []
                
        except Exception as e:
            logger.error(f"Error in _get_emails_with_retry for {account.email}: {str(e)}")
            return []
    
    def get_email_attachments(self, access_token, message_id, proxies=None):
        """Get email attachments from Outlook"""
        try:
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            url = f'https://graph.microsoft.com/v1.0/me/messages/{message_id}/attachments'
            response = requests.get(url, headers=headers, proxies=proxies)
            
            if response.status_code == 200:
                attachments_data = response.json().get('value', [])
                attachments = []
                
                for attachment in attachments_data:
                    if attachment.get('@odata.type') == '#microsoft.graph.fileAttachment':
                        attachments.append({
                            'filename': attachment.get('name', 'attachment'),
                            'content': base64.b64decode(attachment.get('contentBytes', '')),
                            'content_type': attachment.get('contentType', 'application/octet-stream')
                        })
                
                return attachments
            else:
                logger.warning(f"Failed to get attachments for message {message_id}: {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"Error getting attachments for message {message_id}: {str(e)}")
            return []
    
    def create_forward_message(self, email, attachments=None, rule=None):
        """Create forward message with rule-specific modifications"""
        try:
            # Extract email content
            subject = email.get('subject', 'No Subject')
            sender = email.get('from', {}).get('emailAddress', {})
            sender_address = sender.get('address', 'Unknown Sender')
            sender_name = sender.get('name', sender_address)
            received_date = email.get('receivedDateTime', '')
            
            # Apply rule modifications
            if rule and rule.add_prefix:
                subject = f"{rule.add_prefix} {subject}"
            
            # Create email body
            body_content = email.get('body', {}).get('content', '')
            body_type = email.get('body', {}).get('contentType', 'text')
            
            # Convert HTML to text if needed
            if body_type.lower() == 'html':
                text_content = self.h2t.handle(body_content)
            else:
                text_content = body_content
            
            # Create forward header
            forward_header = f"""
--- Forwarded Message ---
From: {sender_name} <{sender_address}>
Date: {received_date}
Subject: {email.get('subject', 'No Subject')}

"""
            
            full_body = forward_header + text_content
            
            # Determine if we should include attachments
            include_attachments = True
            if rule and not rule.forward_attachments:
                include_attachments = False
                attachments = None
            
            return {
                'subject': subject,
                'body': full_body,
                'attachments': attachments if include_attachments else None,
                'is_html': body_type.lower() == 'html'
            }
            
        except Exception as e:
            logger.error(f"Error creating forward message: {str(e)}")
            return None
    
    def forward_emails(self, account, db, max_emails=1000):
        """Forward emails from an Outlook account using rules to determine Gmail targets"""
        from .models import ForwardingHistory
        
        result = {
            'success': 0,
            'failed': 0,
            'errors': [],
            'processed_rules': {}
        }
        
        try:
            # Check if token is expired and refresh if needed
            needs_refresh = (
                account.token_expires_at and 
                account.token_expires_at <= datetime.utcnow() + timedelta(minutes=5)  # Refresh 5 minutes before expiry
            )
            
            if needs_refresh and account.refresh_token:
                logger.info(f"Token expires soon for {account.email}, refreshing...")
                refresh_token = self.microsoft_auth.decrypt_token(account.refresh_token)
                token_result = self.microsoft_auth.refresh_access_token(refresh_token)
                
                if token_result and 'error' not in token_result:
                    # Update tokens
                    account.access_token = self.microsoft_auth.encrypt_token(token_result['access_token'])
                    account.token_expires_at = datetime.utcnow() + timedelta(seconds=token_result['expires_in'])
                    
                    # Update refresh token if a new one was provided
                    if token_result.get('refresh_token') and token_result['refresh_token'] != refresh_token:
                        account.refresh_token = self.microsoft_auth.encrypt_token(token_result['refresh_token'])
                        logger.info(f"Updated refresh token for {account.email}")
                    
                    # Reset error counters
                    account.consecutive_errors = 0
                    account.last_error = None
                    
                    db.session.commit()
                    logger.info(f"Successfully refreshed token for {account.email}")
                    
                else:
                    # Token refresh failed
                    error_msg = f"Failed to refresh token for {account.email}"
                    if token_result:
                        if 'message' in token_result:
                            error_msg += f": {token_result['message']}"
                        elif 'error_description' in token_result:
                            error_msg += f": {token_result['error_description']}"
                        
                        # Check if user needs to re-authenticate
                        if token_result.get('requires_reauth') or token_result.get('error') in ['invalid_grant', 'different_client_id']:
                            account.is_active = False
                            error_msg += " (Account deactivated - requires re-authentication)"
                            logger.warning(f"Deactivating account {account.email} - requires re-authentication")
                    
                    account.last_error = error_msg
                    account.consecutive_errors += 1
                    db.session.commit()
                    result['errors'].append(error_msg)
                    return result
            elif not account.refresh_token:
                error_msg = f"No refresh token available for {account.email}"
                account.last_error = error_msg
                account.consecutive_errors += 1
                db.session.commit()
                result['errors'].append(error_msg)
                return result
            
            # Get access token
            access_token = self.microsoft_auth.decrypt_token(account.access_token)
            if not access_token:
                error_msg = f"No access token available for {account.email}"
                result['errors'].append(error_msg)
                return result
            
            # Get emails - with retry on 401 error
            emails = self._get_emails_with_retry(access_token, account, max_emails, db)
            
            if not emails:
                logger.info(f"No emails to process for {account.email}")
                return result
            
            # Set up proxy if needed
            proxies = None
            if account.proxy_host and account.proxy_port:
                proxy_url = f"http://{account.proxy_host}:{account.proxy_port}"
                if account.proxy_username and account.proxy_password:
                    proxy_url = f"http://{account.proxy_username}:{account.proxy_password}@{account.proxy_host}:{account.proxy_port}"
                proxies = {'http': proxy_url, 'https': proxy_url}
            
            # Process each email
            for email in tqdm(emails, desc=f"Processing emails for {account.email}"):
                try:
                    # Check if already forwarded
                    existing = ForwardingHistory.query.filter_by(
                        account_id=account.id,
                        outlook_message_id=email['id']
                    ).first()
                    
                    if existing and existing.status == 'success':
                        continue
                    
                    # Evaluate forwarding rules
                    rule_result = self.rule_engine.evaluate_rules(account, email)
                    
                    if not rule_result:
                        # No matching rule found
                        logger.debug(f"No forwarding rule matched for email: {email.get('subject', 'No Subject')}")
                        continue
                    
                    rule, gmail_account = rule_result
                    
                    # Track rule usage
                    rule_key = f"{rule.id}_{gmail_account.id}"
                    if rule_key not in result['processed_rules']:
                        result['processed_rules'][rule_key] = {
                            'rule_name': rule.rule_name,
                            'gmail_account': gmail_account.email,
                            'count': 0
                        }
                    result['processed_rules'][rule_key]['count'] += 1
                    
                    # Get attachments if email has them and rule allows them
                    attachments = None
                    if email.get('hasAttachments', False) and rule.forward_attachments:
                        attachments = self.get_email_attachments(access_token, email['id'], proxies)
                    
                    # Create forward message
                    forward_msg = self.create_forward_message(email, attachments, rule)
                    
                    if not forward_msg:
                        result['failed'] += 1
                        result['errors'].append(f"Failed to create forward message for {email['id']}")
                        continue
                    
                    # Send to Gmail
                    gmail_id = self.gmail_service.send_email(
                        gmail_account,
                        forward_msg['subject'],
                        forward_msg['body'],
                        forward_msg['attachments'],
                        forward_msg['is_html']
                    )
                    
                    # Record the forwarding attempt
                    history = ForwardingHistory(
                        account_id=account.id,
                        gmail_account_id=gmail_account.id,
                        rule_id=rule.id,
                        outlook_message_id=email['id'],
                        subject=email.get('subject', 'No Subject')[:500],
                        sender=email.get('from', {}).get('emailAddress', {}).get('address', ''),
                        received_date=datetime.fromisoformat(email.get('receivedDateTime', '').replace('Z', '+00:00')) if email.get('receivedDateTime') else None,
                        gmail_message_id=gmail_id,
                        status='success' if gmail_id else 'failed',
                        has_attachments=email.get('hasAttachments', False),
                        error_message=None if gmail_id else "Failed to send via Gmail API"
                    )
                    
                    db.session.add(history)
                    
                    if gmail_id:
                        result['success'] += 1
                        # Update statistics
                        account.total_emails_forwarded += 1
                        gmail_account.total_emails_received += 1
                        rule.emails_processed += 1
                        rule.last_used = datetime.utcnow()
                        gmail_account.last_used = datetime.utcnow()
                        logger.info(f"Forwarded email '{email.get('subject', 'No Subject')}' to {gmail_account.email}")
                    else:
                        result['failed'] += 1
                        account.total_emails_failed += 1
                        gmail_account.total_emails_failed += 1
                        result['errors'].append(f"Failed to send email {email['id']} to {gmail_account.email}")
                    
                    # Commit after each email to avoid losing progress
                    db.session.commit()
                    
                    # Rate limiting
                    time.sleep(0.1)
                    
                except Exception as e:
                    result['failed'] += 1
                    error_msg = f"Error processing email {email.get('id', 'unknown')}: {str(e)}"
                    result['errors'].append(error_msg)
                    logger.error(error_msg)
                    
                    # Record failed attempt
                    try:
                        history = ForwardingHistory(
                            account_id=account.id,
                            outlook_message_id=email.get('id', ''),
                            subject=email.get('subject', 'No Subject')[:500],
                            status='failed',
                            error_message=str(e)[:1000]
                        )
                        db.session.add(history)
                        db.session.commit()
                    except:
                        pass
            
            # Update account last sync
            account.last_sync = datetime.utcnow()
            account.last_error = None
            account.consecutive_errors = 0
            db.session.commit()
            
        except Exception as e:
            error_msg = f"Error in forward_emails for {account.email}: {str(e)}"
            logger.error(error_msg)
            result['errors'].append(error_msg)
            
            # Update account error info
            account.last_error = str(e)[:1000]
            account.consecutive_errors += 1
            db.session.commit()
        
        return result
    
    def test_forwarding_rule(self, rule, sample_email_data):
        """Test a forwarding rule against sample email data"""
        try:
            matches = self.rule_engine._evaluate_rule(rule, sample_email_data)
            return {
                'matches': matches,
                'rule_name': rule.rule_name,
                'sample_subject': sample_email_data.get('subject', 'No Subject')
            }
        except Exception as e:
            return {
                'matches': False,
                'error': str(e)
            }