import pandas as pd
import logging
from datetime import datetime
from .models import OutlookAccount, db
from .microsoft_auth import MicrosoftAuth

logger = logging.getLogger(__name__)

class CSVImporter:
    """Import Outlook accounts from CSV file"""
    
    def __init__(self, microsoft_auth):
        self.microsoft_auth = microsoft_auth
    
    def _safe_strip(self, value):
        """Safely convert value to string and strip whitespace"""
        if pd.isna(value) or value is None:
            return ''
        return str(value).strip()
    
    def import_accounts(self, csv_file_path):
        """Import accounts from CSV file"""
        try:
            # Read CSV file
            df = pd.read_csv(csv_file_path)
            
            imported_count = 0
            skipped_count = 0
            errors = []
            
            for index, row in df.iterrows():
                try:
                    # Skip if not Outlook provider
                    provider = self._safe_strip(row.get('Provider', '')).lower()
                    if provider != 'outlook':
                        continue
                    
                    username = self._safe_strip(row.get('Username', ''))
                    if not username:
                        continue
                    
                    # Check if account already exists
                    existing = OutlookAccount.query.filter_by(username=username).first()
                    if existing:
                        skipped_count += 1
                        logger.info(f"Account {username} already exists, skipping")
                        continue
                    
                    # Create new account
                    account = OutlookAccount(
                        username=username,
                        email=username,
                        full_name=self._safe_strip(row.get('Full Name', '')),
                        recovery_email=self._safe_strip(row.get('Recovery Email', '')),
                        birthday=self._safe_strip(row.get('Birthday', ''))
                    )
                    
                    # Handle password (encrypt if provided)
                    password = self._safe_strip(row.get('Password', ''))
                    if password:
                        account.password = self.microsoft_auth.encrypt_token(password)
                    
                    # Handle refresh token (encrypt if provided)
                    refresh_token = self._safe_strip(row.get('OAuth2 Refresh Token', ''))
                    if refresh_token:
                        account.refresh_token = self.microsoft_auth.encrypt_token(refresh_token)
                    
                    # Parse proxy information
                    proxy_string = self._safe_strip(row.get('Browser Proxy', ''))
                    if proxy_string:
                        proxy_info = self._parse_proxy_string(proxy_string)
                        if proxy_info:
                            account.proxy_host = proxy_info['host']
                            account.proxy_port = proxy_info['port']
                            account.proxy_username = proxy_info.get('username')
                            account.proxy_password = proxy_info.get('password')
                    
                    # Set initial status
                    account.is_active = True
                    account.consecutive_errors = 0
                    
                    db.session.add(account)
                    imported_count += 1
                    
                    # Commit every 50 accounts
                    if imported_count % 50 == 0:
                        db.session.commit()
                        logger.info(f"Imported {imported_count} accounts so far...")
                    
                except Exception as e:
                    logger.error(f"Error importing row {index}: {str(e)}")
                    errors.append(f"Row {index} (Username: {self._safe_strip(row.get('Username', 'unknown'))}): {str(e)}")
            
            # Final commit
            db.session.commit()
            
            return {
                'imported': imported_count,
                'skipped': skipped_count,
                'errors': errors
            }
            
        except Exception as e:
            logger.error(f"Error reading CSV file: {str(e)}")
            return {
                'imported': 0,
                'skipped': 0,
                'errors': [f"Failed to read CSV: {str(e)}"]
            }
    
    def _parse_proxy_string(self, proxy_string):
        """Parse proxy string from CSV format"""
        # Format appears to be: host:port:username:password
        parts = proxy_string.split(':')
        if len(parts) >= 2:
            try:
                return {
                    'host': parts[0],
                    'port': int(parts[1]),
                    'username': parts[2] if len(parts) > 2 else None,
                    'password': parts[3] if len(parts) > 3 else None
                }
            except ValueError:
                logger.warning(f"Invalid proxy format: {proxy_string}")
                return None
        return None
    
    def update_refresh_tokens(self, csv_file_path):
        """Update refresh tokens for existing accounts from CSV"""
        try:
            df = pd.read_csv(csv_file_path)
            
            updated_count = 0
            not_found_count = 0
            errors = []
            
            for index, row in df.iterrows():
                try:
                    # Skip if not Outlook provider
                    provider = self._safe_strip(row.get('Provider', '')).lower()
                    if provider != 'outlook':
                        continue
                    
                    username = self._safe_strip(row.get('Username', ''))
                    refresh_token = self._safe_strip(row.get('OAuth2 Refresh Token', ''))
                    
                    if not username or not refresh_token:
                        continue
                    
                    # Find existing account
                    account = OutlookAccount.query.filter_by(username=username).first()
                    
                    if account:
                        # Update refresh token
                        account.refresh_token = self.microsoft_auth.encrypt_token(refresh_token)
                        account.is_active = True
                        account.consecutive_errors = 0
                        updated_count += 1
                    else:
                        not_found_count += 1
                        logger.warning(f"Account {username} not found in database")
                    
                    # Commit every 50 updates
                    if updated_count % 50 == 0:
                        db.session.commit()
                        
                except Exception as e:
                    logger.error(f"Error updating row {index}: {str(e)}")
                    errors.append(f"Row {index}: {str(e)}")
            
            # Final commit
            db.session.commit()
            
            return {
                'updated': updated_count,
                'not_found': not_found_count,
                'errors': errors
            }
            
        except Exception as e:
            logger.error(f"Error reading CSV file: {str(e)}")
            return {
                'updated': 0,
                'not_found': 0,
                'errors': [f"Failed to read CSV: {str(e)}"]
            }
    
    def export_accounts(self, output_file_path, include_tokens=False):
        """Export accounts to CSV file"""
        try:
            accounts = OutlookAccount.query.all()
            
            data = []
            for account in accounts:
                row = {
                    'Category': 'Testing',
                    'Provider': 'Outlook',
                    'Username': account.username,
                    'Password': '',  # Don't export passwords
                    'App Password': '',
                    'Service Name': 'Outlook',
                    'Host': 'outlook.office365.com',
                    'Port': 993,
                    'Requires SSL': True,
                    'Folders': 'Junk,Inbox',
                    'Mail Proxy': '',
                    'Browser Proxy': '',
                    'Login Type': 'OAuth2',
                    'OAuth2 Refresh Token': '',
                    'Forwards To Email': '',
                    'Forwarding Method': '',
                    'Account History': f"Last sync: {account.last_sync.isoformat() if account.last_sync else 'Never'}",
                    'Email Aliases': '',
                    'SMTP Host': 'smtp-mail.outlook.com',
                    'SMTP Port': 587,
                    'SMTP Requires SSL': True,
                    'OAuth2 Client ID': '',
                    'Recovery Email': account.recovery_email or '',
                    '2FA Secret Key': '',
                    'Security Answer': '',
                    'Recovery Code': '',
                    'Birthday': account.birthday or '',
                    'Full Name': account.full_name or '',
                    'OAuth2 Client Secret': '',
                    'Phone Number': ''
                }
                
                # Add proxy info if available
                if account.proxy_host and account.proxy_port:
                    proxy_parts = [str(account.proxy_host), str(account.proxy_port)]
                    if account.proxy_username:
                        proxy_parts.append(account.proxy_username)
                    if account.proxy_password:
                        proxy_parts.append(account.proxy_password)
                    row['Browser Proxy'] = ':'.join(proxy_parts)
                
                # Include tokens if requested
                if include_tokens and account.refresh_token:
                    row['OAuth2 Refresh Token'] = self.microsoft_auth.decrypt_token(account.refresh_token)
                
                data.append(row)
            
            # Create DataFrame and save to CSV
            df = pd.DataFrame(data)
            df.to_csv(output_file_path, index=False)
            
            return {
                'exported': len(data),
                'file': output_file_path
            }
            
        except Exception as e:
            logger.error(f"Error exporting accounts: {str(e)}")
            return {
                'exported': 0,
                'error': str(e)
            } 