#!/usr/bin/env python3
import click
import os
import sys
from datetime import datetime, timedelta
from tabulate import tabulate
import pandas as pd

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from config.config import config
from src.models import db, OutlookAccount, ForwardingHistory, ForwardingJob
from src.microsoft_auth import MicrosoftAuth
from src.email_forwarder import EmailForwarder
from src.csv_importer import CSVImporter
from src.scheduler import ForwardingScheduler

# Create Flask app for database context
app = Flask(__name__)
app.config.from_object(config[os.environ.get('FLASK_ENV', 'development')])
db.init_app(app)

# Initialize services
microsoft_auth = MicrosoftAuth(
    app.config['MICROSOFT_CLIENT_ID'],
    app.config['MICROSOFT_CLIENT_SECRET']
)
csv_importer = CSVImporter(microsoft_auth)

@click.group()
def cli():
    """Outlook to Gmail Forwarder CLI"""
    pass

@cli.command()
@click.option('--csv-file', required=True, help='Path to CSV file with accounts')
@click.option('--update-only', is_flag=True, help='Only update existing accounts')
def import_accounts(csv_file, update_only):
    """Import accounts from CSV file"""
    with app.app_context():
        click.echo(f"Importing accounts from {csv_file}...")
        
        if update_only:
            result = csv_importer.update_refresh_tokens(csv_file)
            click.echo(f"✓ Updated {result['updated']} accounts")
            click.echo(f"✗ {result['not_found']} accounts not found")
        else:
            result = csv_importer.import_accounts(csv_file)
            click.echo(f"✓ Imported {result['imported']} accounts")
            click.echo(f"⚠ Skipped {result['skipped']} existing accounts")
        
        if result['errors']:
            click.echo("\nErrors:")
            for error in result['errors'][:10]:
                click.echo(f"  - {error}")

@cli.command()
@click.option('--output', default='accounts_export.csv', help='Output CSV file')
@click.option('--include-tokens', is_flag=True, help='Include refresh tokens in export')
def export_accounts(output, include_tokens):
    """Export accounts to CSV file"""
    with app.app_context():
        click.echo(f"Exporting accounts to {output}...")
        
        result = csv_importer.export_accounts(output, include_tokens)
        
        if result['exported'] > 0:
            click.echo(f"✓ Exported {result['exported']} accounts to {output}")
        else:
            click.echo("✗ No accounts to export")

@cli.command()
@click.option('--active-only', is_flag=True, help='Show only active accounts')
@click.option('--limit', default=20, help='Number of accounts to show')
def list_accounts(active_only, limit):
    """List all accounts"""
    with app.app_context():
        query = OutlookAccount.query
        
        if active_only:
            query = query.filter_by(is_active=True)
        
        accounts = query.limit(limit).all()
        
        if not accounts:
            click.echo("No accounts found")
            return
        
        data = []
        for acc in accounts:
            data.append([
                acc.id,
                acc.username,
                '✓' if acc.is_active else '✗',
                acc.last_sync.strftime('%Y-%m-%d %H:%M') if acc.last_sync else 'Never',
                acc.total_emails_forwarded,
                acc.consecutive_errors
            ])
        
        headers = ['ID', 'Username', 'Active', 'Last Sync', 'Forwarded', 'Errors']
        click.echo(tabulate(data, headers=headers, tablefmt='grid'))

@cli.command()
@click.argument('account_id', type=int)
def account_info(account_id):
    """Show detailed account information"""
    with app.app_context():
        account = OutlookAccount.query.get(account_id)
        
        if not account:
            click.echo(f"Account {account_id} not found")
            return
        
        click.echo(f"\nAccount Details:")
        click.echo(f"  ID: {account.id}")
        click.echo(f"  Username: {account.username}")
        click.echo(f"  Full Name: {account.full_name or 'N/A'}")
        click.echo(f"  Active: {'Yes' if account.is_active else 'No'}")
        click.echo(f"  Created: {account.created_at.strftime('%Y-%m-%d %H:%M')}")
        click.echo(f"  Last Sync: {account.last_sync.strftime('%Y-%m-%d %H:%M') if account.last_sync else 'Never'}")
        click.echo(f"  Emails Forwarded: {account.total_emails_forwarded}")
        click.echo(f"  Emails Failed: {account.total_emails_failed}")
        click.echo(f"  Consecutive Errors: {account.consecutive_errors}")
        
        if account.last_error:
            click.echo(f"  Last Error: {account.last_error}")
        
        # Show recent forwarding history
        history = ForwardingHistory.query.filter_by(
            account_id=account_id
        ).order_by(ForwardingHistory.forwarded_at.desc()).limit(10).all()
        
        if history:
            click.echo(f"\nRecent Forwarding History:")
            for h in history:
                status_icon = '✓' if h.status == 'success' else '✗'
                click.echo(f"  {status_icon} {h.forwarded_at.strftime('%Y-%m-%d %H:%M')} - {h.subject[:50]}")

@cli.command()
@click.argument('account_id', type=int)
@click.option('--activate/--deactivate', default=True, help='Activate or deactivate account')
def toggle_account(account_id, activate):
    """Toggle account active status"""
    with app.app_context():
        account = OutlookAccount.query.get(account_id)
        
        if not account:
            click.echo(f"Account {account_id} not found")
            return
        
        account.is_active = activate
        db.session.commit()
        
        status = 'activated' if activate else 'deactivated'
        click.echo(f"✓ Account {account.username} {status}")

@cli.command()
@click.option('--max-emails', default=100, help='Maximum emails to forward per account')
@click.option('--account-id', type=int, help='Forward for specific account only')
def forward_now(max_emails, account_id):
    """Manually trigger email forwarding"""
    with app.app_context():
        click.echo("Starting email forwarding...")
        
        # Initialize forwarder
        forwarder = EmailForwarder(
            microsoft_auth,
            app.config['GMAIL_CREDENTIALS_FILE'],
            app.config['GMAIL_TARGET_EMAIL']
        )
        
        if not forwarder.initialize_gmail_service():
            click.echo("✗ Failed to initialize Gmail service")
            return
        
        # Get accounts
        if account_id:
            accounts = [OutlookAccount.query.get(account_id)]
            if not accounts[0]:
                click.echo(f"Account {account_id} not found")
                return
        else:
            accounts = OutlookAccount.query.filter_by(is_active=True).all()
        
        click.echo(f"Processing {len(accounts)} account(s)...")
        
        total_success = 0
        total_failed = 0
        
        for account in accounts:
            click.echo(f"\n→ Processing {account.username}...")
            
            result = forwarder.forward_emails(account, db, max_emails)
            
            total_success += result['success']
            total_failed += result['failed']
            
            click.echo(f"  ✓ Forwarded: {result['success']}")
            click.echo(f"  ✗ Failed: {result['failed']}")
            
            if result['errors']:
                click.echo("  Errors:")
                for error in result['errors'][:3]:
                    click.echo(f"    - {error}")
        
        click.echo(f"\nTotal: {total_success} forwarded, {total_failed} failed")

@cli.command()
def jobs():
    """List recent forwarding jobs"""
    with app.app_context():
        recent_jobs = ForwardingJob.query.order_by(
            ForwardingJob.created_at.desc()
        ).limit(10).all()
        
        if not recent_jobs:
            click.echo("No jobs found")
            return
        
        data = []
        for job in recent_jobs:
            duration = 'N/A'
            if job.started_at and job.completed_at:
                duration = str(job.completed_at - job.started_at).split('.')[0]
            
            data.append([
                job.id,
                job.job_type,
                job.status,
                job.created_at.strftime('%Y-%m-%d %H:%M'),
                f"{job.processed_accounts}/{job.total_accounts}",
                job.forwarded_emails,
                job.failed_emails,
                duration
            ])
        
        headers = ['ID', 'Type', 'Status', 'Created', 'Accounts', 'Success', 'Failed', 'Duration']
        click.echo(tabulate(data, headers=headers, tablefmt='grid'))

@cli.command()
def stats():
    """Show system statistics"""
    with app.app_context():
        total_accounts = OutlookAccount.query.count()
        active_accounts = OutlookAccount.query.filter_by(is_active=True).count()
        
        total_forwarded = db.session.query(
            db.func.sum(OutlookAccount.total_emails_forwarded)
        ).scalar() or 0
        
        total_failed = db.session.query(
            db.func.sum(OutlookAccount.total_emails_failed)
        ).scalar() or 0
        
        # Get today's stats
        from datetime import date
        today_forwarded = ForwardingHistory.query.filter(
            db.func.date(ForwardingHistory.forwarded_at) == date.today(),
            ForwardingHistory.status == 'success'
        ).count()
        
        click.echo("\nSystem Statistics:")
        click.echo(f"  Total Accounts: {total_accounts}")
        click.echo(f"  Active Accounts: {active_accounts}")
        click.echo(f"  Total Emails Forwarded: {total_forwarded}")
        click.echo(f"  Total Emails Failed: {total_failed}")
        click.echo(f"  Forwarded Today: {today_forwarded}")
        
        # Get problematic accounts
        problematic = OutlookAccount.query.filter(
            OutlookAccount.consecutive_errors > 5
        ).all()
        
        if problematic:
            click.echo(f"\nProblematic Accounts ({len(problematic)}):")
            for acc in problematic[:5]:
                click.echo(f"  - {acc.username}: {acc.consecutive_errors} errors")

@cli.command()
@click.argument('account_id', type=int)
def test_account(account_id):
    """Test account connection"""
    with app.app_context():
        account = OutlookAccount.query.get(account_id)
        
        if not account:
            click.echo(f"Account {account_id} not found")
            return
        
        click.echo(f"Testing account {account.username}...")
        
        if not account.refresh_token:
            click.echo("✗ No refresh token available")
            return
        
        try:
            refresh_token = microsoft_auth.decrypt_token(account.refresh_token)
            token_result = microsoft_auth.refresh_access_token(refresh_token)
            
            if token_result and 'error' not in token_result:
                click.echo("✓ Successfully refreshed access token")
                
                # Update tokens in database
                account.access_token = microsoft_auth.encrypt_token(token_result['access_token'])
                account.token_expires_at = datetime.utcnow() + timedelta(seconds=token_result['expires_in'])
                
                # Update refresh token if new one provided
                if token_result.get('refresh_token') and token_result['refresh_token'] != refresh_token:
                    account.refresh_token = microsoft_auth.encrypt_token(token_result['refresh_token'])
                    click.echo("✓ Updated refresh token")
                
                db.session.commit()
                
                # Test getting user info
                user_info = microsoft_auth.get_user_info(token_result['access_token'])
                if user_info:
                    click.echo(f"✓ Connected as: {user_info.get('displayName', 'Unknown')}")
                    click.echo(f"  Email: {user_info.get('mail', user_info.get('userPrincipalName', 'Unknown'))}")
                else:
                    click.echo("⚠ Could not retrieve user information")
            else:
                error_msg = "Failed to refresh token"
                if token_result and 'message' in token_result:
                    error_msg = token_result['message']
                click.echo(f"✗ {error_msg}")
                
                # Provide additional guidance based on error type
                if token_result and token_result.get('error') == 'invalid_token':
                    click.echo("\n  The refresh token is invalid or expired.")
                    click.echo("  The account needs to re-authenticate through the OAuth flow.")
                elif token_result and token_result.get('error') == 'provider_error':
                    click.echo("\n  This appears to be a temporary issue with Microsoft's identity provider.")
                    click.echo("  Please try again in a few minutes.")
                
        except Exception as e:
            click.echo(f"✗ Error: {str(e)}")

@cli.command()
def init_db():
    """Initialize database"""
    with app.app_context():
        click.echo("Creating database tables...")
        db.create_all()
        click.echo("✓ Database initialized")
        
        # Create default admin user
        from src.models import User
        from werkzeug.security import generate_password_hash
        
        if not User.query.first():
            admin = User(
                username='admin',
                password_hash=generate_password_hash('admin123')
            )
            db.session.add(admin)
            db.session.commit()
            click.echo("✓ Created default admin user (username: admin, password: admin123)")

@cli.command()
def create_env():
    """Create example .env file"""
    env_content = """# Flask Configuration
FLASK_ENV=development
SECRET_KEY=your-secret-key-here

# Database
DATABASE_URL=sqlite:///outlook2gmail.db

# Microsoft OAuth
MICROSOFT_CLIENT_ID=your-client-id
MICROSOFT_CLIENT_SECRET=your-client-secret

# Gmail Configuration
GMAIL_TARGET_EMAIL=target@gmail.com
GMAIL_CREDENTIALS_FILE=config/gmail_credentials.json

# Forwarding Settings
BATCH_SIZE=100
MAX_EMAILS_PER_RUN=1000
FORWARD_INTERVAL_MINUTES=30

# Optional Redis Configuration
# REDIS_URL=redis://localhost:6379/0
"""
    
    with open('.env.example', 'w') as f:
        f.write(env_content)
    
    click.echo("✓ Created .env.example file")
    click.echo("  Copy to .env and update with your configuration")

@cli.command()
@click.argument('account_id', type=int, required=False)
@click.option('--all-failed', is_flag=True, help='Re-authenticate all accounts with errors')
def reauth(account_id, all_failed):
    """Generate re-authentication URL for accounts"""
    with app.app_context():
        if all_failed:
            # Get all accounts with consecutive errors
            accounts = OutlookAccount.query.filter(
                OutlookAccount.consecutive_errors > 0
            ).all()
            
            if not accounts:
                click.echo("No accounts with errors found")
                return
                
            click.echo(f"Found {len(accounts)} accounts needing re-authentication:\n")
            
            for account in accounts:
                click.echo(f"Account: {account.username}")
                click.echo(f"  Errors: {account.consecutive_errors}")
                click.echo(f"  Last Error: {account.last_error[:100] if account.last_error else 'N/A'}")
                click.echo("")
                
            click.echo("\nTo re-authenticate these accounts, you need to:")
            click.echo("1. Have each user sign in through the OAuth flow")
            click.echo("2. Update their refresh tokens in the database")
            
        elif account_id:
            account = OutlookAccount.query.get(account_id)
            
            if not account:
                click.echo(f"Account {account_id} not found")
                return
                
            click.echo(f"Account: {account.username}")
            click.echo(f"Status: {'Active' if account.is_active else 'Inactive'}")
            click.echo(f"Consecutive Errors: {account.consecutive_errors}")
            
            if account.last_error:
                click.echo(f"Last Error: {account.last_error}")
                
            click.echo("\nTo re-authenticate this account:")
            click.echo("1. The user needs to sign in through the OAuth flow")
            click.echo("2. Capture the new refresh token")
            click.echo("3. Update it using: cli.py update-token <account_id> <new_refresh_token>")
            
            # Generate OAuth URL
            redirect_uri = "http://localhost:5000/auth/callback"
            auth_url = microsoft_auth.get_auth_url(redirect_uri, state=str(account_id))
            
            click.echo(f"\nOAuth URL:\n{auth_url}")
            
        else:
            click.echo("Please specify an account ID or use --all-failed flag")

@cli.command()
@click.argument('account_id', type=int)
@click.argument('refresh_token')
def update_token(account_id, refresh_token):
    """Update refresh token for an account"""
    with app.app_context():
        account = OutlookAccount.query.get(account_id)
        
        if not account:
            click.echo(f"Account {account_id} not found")
            return
            
        try:
            # Test the new token first
            token_result = microsoft_auth.refresh_access_token(refresh_token)
            
            if token_result and 'error' not in token_result:
                # Update tokens
                account.refresh_token = microsoft_auth.encrypt_token(refresh_token)
                account.access_token = microsoft_auth.encrypt_token(token_result['access_token'])
                account.token_expires_at = datetime.utcnow() + timedelta(seconds=token_result['expires_in'])
                account.consecutive_errors = 0
                account.last_error = None
                account.is_active = True
                
                db.session.commit()
                
                click.echo(f"✓ Successfully updated token for {account.username}")
                click.echo("  Account is now active and ready for forwarding")
                
            else:
                error_msg = "Invalid token"
                if token_result and 'message' in token_result:
                    error_msg = token_result['message']
                click.echo(f"✗ Failed to validate token: {error_msg}")
                
        except Exception as e:
            click.echo(f"✗ Error updating token: {str(e)}")

if __name__ == '__main__':
    # Add tabulate to requirements if not present
    import subprocess
    subprocess.run([sys.executable, '-m', 'pip', 'install', 'tabulate'], capture_output=True)
    
    cli() 