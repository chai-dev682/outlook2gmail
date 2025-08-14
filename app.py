import os
import logging
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_file
from flask_migrate import Migrate
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import json

from config.config import config
from src.models import db, User, OutlookAccount, ForwardingHistory, ForwardingJob, GmailAccount, ForwardingRule
from src.microsoft_auth import MicrosoftAuth
from src.email_forwarder import EmailForwarder
from src.enhanced_email_forwarder import EnhancedEmailForwarder
from src.gmail_service import GmailService
from src.forwarding_rule_engine import ForwardingRuleEngine
from src.csv_importer import CSVImporter
from src.scheduler import ForwardingScheduler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
app.config.from_object(config[os.environ.get('FLASK_ENV', 'development')])

# Initialize extensions
db.init_app(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Initialize scheduler
scheduler = ForwardingScheduler()

# Initialize services
microsoft_auth = None
csv_importer = None
gmail_service = None
rule_engine = None

def initialize_services():
    """Initialize services"""
    global microsoft_auth, csv_importer, gmail_service, rule_engine
    
    # Create necessary directories
    os.makedirs('logs', exist_ok=True)
    os.makedirs('config', exist_ok=True)
    os.makedirs('uploads', exist_ok=True)
    
    with app.app_context():
        # Create tables
        db.create_all()
        
        # Create default admin user if none exists
        if not User.query.first():
            admin = User(
                username='admin',
                password_hash=generate_password_hash('admin123')
            )
            db.session.add(admin)
            db.session.commit()
            logger.info("Created default admin user")
    
    # Initialize Microsoft auth
    microsoft_auth = MicrosoftAuth(
        app.config['MICROSOFT_CLIENT_ID'],
        app.config['MICROSOFT_CLIENT_SECRET']
    )
    
    # Initialize Gmail service
    gmail_service = GmailService()
    
    # Initialize rule engine
    rule_engine = ForwardingRuleEngine()
    
    # Initialize CSV importer
    csv_importer = CSVImporter(microsoft_auth)
    
    # Initialize scheduler
    scheduler.init_app(app)

# Initialize services when app starts
with app.app_context():
    initialize_services()

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Authentication routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'error')
    
    return render_template('login.html')

@app.route('/logout')
# @login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/auth/callback')
def auth_callback():
    """Handle OAuth callback from Microsoft"""
    code = request.args.get('code')
    state = request.args.get('state')  # Can contain account_id for re-auth
    error = request.args.get('error')
    error_description = request.args.get('error_description')
    
    if error:
        flash(f'Authentication error: {error_description or error}', 'error')
        return redirect(url_for('accounts'))
    
    if not code:
        flash('No authorization code received', 'error')
        return redirect(url_for('accounts'))
    
    try:
        # Get tokens using the authorization code
        redirect_uri = app.config['MICROSOFT_REDIRECT_URI']
        result = microsoft_auth.acquire_token_by_code(code, redirect_uri)
        
        if 'access_token' in result:
            # Get user info to identify the account
            user_info = microsoft_auth.get_user_info(result['access_token'])
            
            if user_info:
                email = user_info.get('mail') or user_info.get('userPrincipalName')
                
                # Check if we're updating an existing account (re-auth)
                if state and state.isdigit():
                    account = OutlookAccount.query.get(int(state))
                    if account:
                        # Update existing account tokens
                        account.access_token = microsoft_auth.encrypt_token(result['access_token'])
                        account.refresh_token = microsoft_auth.encrypt_token(result.get('refresh_token'))
                        account.token_expires_at = datetime.utcnow() + timedelta(seconds=result.get('expires_in', 3600))
                        account.last_error = None
                        account.consecutive_errors = 0
                        account.is_active = True
                        db.session.commit()
                        flash(f'Successfully re-authenticated account: {email}', 'success')
                        return redirect(url_for('account_detail', account_id=account.id))
                
                # Check if account already exists
                existing_account = OutlookAccount.query.filter_by(email=email).first()
                if existing_account:
                    # Update existing account
                    existing_account.access_token = microsoft_auth.encrypt_token(result['access_token'])
                    existing_account.refresh_token = microsoft_auth.encrypt_token(result.get('refresh_token'))
                    existing_account.token_expires_at = datetime.utcnow() + timedelta(seconds=result.get('expires_in', 3600))
                    existing_account.last_error = None
                    existing_account.consecutive_errors = 0
                    existing_account.is_active = True
                    db.session.commit()
                    flash(f'Updated existing account: {email}', 'success')
                else:
                    # Create new account
                    new_account = OutlookAccount(
                        email=email,
                        display_name=user_info.get('displayName', email),
                        access_token=microsoft_auth.encrypt_token(result['access_token']),
                        refresh_token=microsoft_auth.encrypt_token(result.get('refresh_token')),
                        token_expires_at=datetime.utcnow() + timedelta(seconds=result.get('expires_in', 3600))
                    )
                    db.session.add(new_account)
                    db.session.commit()
                    flash(f'Successfully added account: {email}', 'success')
            else:
                flash('Could not retrieve user information', 'error')
        else:
            error_msg = result.get('error_description', result.get('error', 'Unknown error'))
            flash(f'Failed to obtain access token: {error_msg}', 'error')
            
    except Exception as e:
        logger.error(f"OAuth callback error: {str(e)}")
        flash(f'Authentication error: {str(e)}', 'error')
    
    return redirect(url_for('accounts'))

# Main routes
@app.route('/')
# @login_required
def dashboard():
    """Main dashboard"""
    # Get Outlook account statistics
    total_accounts = OutlookAccount.query.count()
    active_accounts = OutlookAccount.query.filter_by(is_active=True).count()
    
    # Get Gmail account statistics
    total_gmail_accounts = GmailAccount.query.count()
    active_gmail_accounts = GmailAccount.query.filter_by(is_active=True).count()
    
    # Get forwarding rules statistics
    total_rules = ForwardingRule.query.count()
    active_rules = ForwardingRule.query.filter_by(is_active=True).count()
    
    # Get recent forwarding history
    recent_forwards = ForwardingHistory.query.order_by(
        ForwardingHistory.forwarded_at.desc()
    ).limit(10).all()
    
    # Get recent jobs
    recent_jobs = ForwardingJob.query.order_by(
        ForwardingJob.created_at.desc()
    ).limit(5).all()
    
    # Get scheduler status
    scheduler_status = scheduler.get_status()
    
    # Get total forwarding statistics
    total_forwarded = db.session.query(
        db.func.sum(OutlookAccount.total_emails_forwarded)
    ).scalar() or 0
    
    total_failed = db.session.query(
        db.func.sum(OutlookAccount.total_emails_failed)
    ).scalar() or 0
    
    return render_template('dashboard.html',
        total_accounts=total_accounts,
        active_accounts=active_accounts,
        total_gmail_accounts=total_gmail_accounts,
        active_gmail_accounts=active_gmail_accounts,
        total_rules=total_rules,
        active_rules=active_rules,
        total_forwarded=total_forwarded,
        total_failed=total_failed,
        recent_forwards=recent_forwards,
        recent_jobs=recent_jobs,
        scheduler_status=scheduler_status
    )

@app.route('/accounts')
# @login_required
def accounts():
    """List all Outlook accounts"""
    accounts = OutlookAccount.query.all()
    
    # Calculate stats for each account
    for account in accounts:
        account.emails_forwarded = ForwardingHistory.query.filter_by(
            account_id=account.id,
            status='success'
        ).count()
    
    return render_template('accounts.html', accounts=accounts)

@app.route('/accounts/<int:account_id>/reauth')
# @login_required
def reauth_account(account_id):
    """Re-authenticate an existing account"""
    account = OutlookAccount.query.get_or_404(account_id)
    redirect_uri = app.config['MICROSOFT_REDIRECT_URI']
    # Pass account ID in state to identify which account is being re-authenticated
    auth_url = microsoft_auth.get_auth_url(redirect_uri, state=str(account_id))
    return redirect(auth_url)

@app.route('/accounts/<int:account_id>')
# @login_required
def account_detail(account_id):
    """Account detail page"""
    account = OutlookAccount.query.get_or_404(account_id)
    
    # Get forwarding history
    history = ForwardingHistory.query.filter_by(
        account_id=account_id
    ).order_by(ForwardingHistory.forwarded_at.desc()).limit(50).all()
    
    return render_template('account_detail.html', 
        account=account, 
        history=history
    )

@app.route('/api/accounts/<int:account_id>/toggle', methods=['POST'])
# @login_required
def toggle_account(account_id):
    """Toggle account active status"""
    account = OutlookAccount.query.get_or_404(account_id)
    account.is_active = not account.is_active
    db.session.commit()
    
    return jsonify({
        'success': True,
        'is_active': account.is_active
    })

@app.route('/api/accounts/<int:account_id>/test', methods=['POST'])
# @login_required
def test_account(account_id):
    """Test account connection"""
    account = OutlookAccount.query.get_or_404(account_id)
    
    try:
        # Test token refresh
        if account.refresh_token:
            refresh_token = microsoft_auth.decrypt_token(account.refresh_token)
            token_result = microsoft_auth.refresh_access_token(refresh_token)
            
            if token_result and 'error' not in token_result:
                # Update tokens if successful
                account.access_token = microsoft_auth.encrypt_token(token_result['access_token'])
                account.token_expires_at = datetime.utcnow() + timedelta(seconds=token_result['expires_in'])
                
                # Update refresh token if new one provided
                if token_result.get('refresh_token') and token_result['refresh_token'] != refresh_token:
                    account.refresh_token = microsoft_auth.encrypt_token(token_result['refresh_token'])
                
                db.session.commit()
                
                return jsonify({
                    'success': True,
                    'message': 'Account connection successful'
                })
            else:
                error_msg = 'Failed to refresh token'
                if token_result and 'message' in token_result:
                    error_msg = token_result['message']
                
                return jsonify({
                    'success': False,
                    'message': error_msg
                })
        else:
            return jsonify({
                'success': False,
                'message': 'No refresh token available'
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        })

@app.route('/import', methods=['GET', 'POST'])
# @login_required
def import_accounts():
    """Import accounts from CSV"""
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file uploaded', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(request.url)
        
        if file and file.filename.endswith('.csv'):
            # Save uploaded file
            filepath = os.path.join('uploads', f'import_{datetime.now().timestamp()}.csv')
            file.save(filepath)
            
            try:
                # Import accounts
                result = csv_importer.import_accounts(filepath)
                
                flash(f'Import completed: {result["imported"]} imported, {result["skipped"]} skipped', 'success')
                
                if result['errors']:
                    for error in result['errors'][:5]:
                        flash(error, 'warning')
                
                # Clean up
                os.remove(filepath)
                
                return redirect(url_for('accounts'))
                
            except Exception as e:
                flash(f'Import failed: {str(e)}', 'error')
                os.remove(filepath)
        else:
            flash('Please upload a CSV file', 'error')
    
    return render_template('import.html')

@app.route('/export')
# @login_required
def export_accounts():
    """Export accounts to CSV"""
    include_tokens = request.args.get('include_tokens', 'false').lower() == 'true'
    
    filepath = f'exports/accounts_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    os.makedirs('exports', exist_ok=True)
    
    result = csv_importer.export_accounts(filepath, include_tokens)
    
    if result['exported'] > 0:
        return send_file(filepath, as_attachment=True)
    else:
        flash('No accounts to export', 'warning')
        return redirect(url_for('accounts'))

@app.route('/jobs')
# @login_required
def jobs():
    """View forwarding jobs"""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    jobs = ForwardingJob.query.order_by(
        ForwardingJob.created_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template('jobs.html', jobs=jobs)

# Gmail OAuth routes
@app.route('/gmail/auth')
# @login_required
def gmail_auth():
    """Initiate Gmail OAuth flow"""
    credentials_file = app.config.get('GMAIL_CREDENTIALS_FILE', 'config/gmail_credentials.json')
    
    if not os.path.exists(credentials_file):
        flash('Gmail credentials file not found. Please configure OAuth credentials.', 'error')
        return redirect(url_for('settings'))
    
    redirect_uri = f"{app.config['APP_URL']}/gmail/callback"
    auth_url = gmail_service.get_auth_url(credentials_file, redirect_uri)
    
    if auth_url:
        return redirect(auth_url)
    else:
        flash('Failed to create Gmail authorization URL', 'error')
        return redirect(url_for('gmail_accounts'))

@app.route('/gmail/callback')
def gmail_auth_callback():
    """Handle Gmail OAuth callback"""
    code = request.args.get('code')
    error = request.args.get('error')
    
    if error:
        flash(f'Gmail authentication error: {error}', 'error')
        return redirect(url_for('gmail_accounts'))
    
    if not code:
        flash('No authorization code received', 'error')
        return redirect(url_for('gmail_accounts'))
    
    try:
        credentials_file = app.config.get('GMAIL_CREDENTIALS_FILE', 'config/gmail_credentials.json')
        redirect_uri = f"{app.config['APP_URL']}/gmail/callback"
        
        # Exchange code for tokens
        token_result = gmail_service.exchange_code_for_tokens(credentials_file, redirect_uri, code)
        
        if token_result:
            # Get user info
            user_info = gmail_service.get_user_info(token_result['access_token'])
            
            if user_info:
                email = user_info.get('email')
                display_name = user_info.get('name', email)
                
                # Check if account already exists
                existing_account = GmailAccount.query.filter_by(email=email).first()
                
                if existing_account:
                    # Update existing account
                    existing_account.access_token = gmail_service.encrypt_token(token_result['access_token'])
                    existing_account.refresh_token = gmail_service.encrypt_token(token_result['refresh_token'])
                    existing_account.token_expires_at = datetime.utcnow() + timedelta(seconds=token_result['expires_in'])
                    existing_account.display_name = display_name
                    existing_account.last_error = None
                    existing_account.consecutive_errors = 0
                    existing_account.is_active = True
                    db.session.commit()
                    flash(f'Updated Gmail account: {email}', 'success')
                else:
                    # Create new account
                    new_account = GmailAccount(
                        email=email,
                        display_name=display_name,
                        access_token=gmail_service.encrypt_token(token_result['access_token']),
                        refresh_token=gmail_service.encrypt_token(token_result['refresh_token']),
                        token_expires_at=datetime.utcnow() + timedelta(seconds=token_result['expires_in'])
                    )
                    db.session.add(new_account)
                    db.session.commit()
                    flash(f'Added Gmail account: {email}', 'success')
            else:
                flash('Could not retrieve Gmail user information', 'error')
        else:
            flash('Failed to obtain Gmail access tokens', 'error')
            
    except Exception as e:
        logger.error(f"Gmail OAuth callback error: {str(e)}")
        flash(f'Gmail authentication error: {str(e)}', 'error')
    
    return redirect(url_for('gmail_accounts'))

# Gmail account management routes
@app.route('/gmail-accounts')
# @login_required
def gmail_accounts():
    """List all Gmail accounts"""
    accounts = GmailAccount.query.all()
    
    # Calculate stats for each account
    for account in accounts:
        account.emails_received = ForwardingHistory.query.filter_by(
            gmail_account_id=account.id,
            status='success'
        ).count()
    
    return render_template('gmail_accounts.html', accounts=accounts)

@app.route('/gmail-accounts/<int:account_id>')
# @login_required
def gmail_account_detail(account_id):
    """Gmail account detail page"""
    account = GmailAccount.query.get_or_404(account_id)
    
    # Get forwarding history
    history = ForwardingHistory.query.filter_by(
        gmail_account_id=account_id
    ).order_by(ForwardingHistory.forwarded_at.desc()).limit(50).all()
    
    # Get forwarding rules
    rules = ForwardingRule.query.filter_by(
        gmail_account_id=account_id
    ).order_by(ForwardingRule.priority.asc()).all()
    
    return render_template('gmail_account_detail.html', 
        account=account, 
        history=history,
        rules=rules
    )

@app.route('/api/gmail-accounts/<int:account_id>/toggle', methods=['POST'])
# @login_required
def toggle_gmail_account(account_id):
    """Toggle Gmail account active status"""
    account = GmailAccount.query.get_or_404(account_id)
    account.is_active = not account.is_active
    db.session.commit()
    
    return jsonify({
        'success': True,
        'is_active': account.is_active
    })

@app.route('/api/gmail-accounts/<int:account_id>/test', methods=['POST'])
# @login_required
def test_gmail_account(account_id):
    """Test Gmail account connection"""
    account = GmailAccount.query.get_or_404(account_id)
    
    try:
        success, message = gmail_service.test_account_connection(account)
        
        if success:
            account.last_error = None
            account.consecutive_errors = 0
            db.session.commit()
        
        return jsonify({
            'success': success,
            'message': message
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        })

# Forwarding rules management
@app.route('/forwarding-rules')
# @login_required
def forwarding_rules():
    """List all forwarding rules"""
    rules = ForwardingRule.query.order_by(
        ForwardingRule.outlook_account_id.asc(),
        ForwardingRule.priority.asc()
    ).all()
    
    return render_template('forwarding_rules.html', rules=rules)

@app.route('/forwarding-rules/create', methods=['GET', 'POST'])
# @login_required
def create_forwarding_rule():
    """Create new forwarding rule"""
    if request.method == 'POST':
        try:
            data = request.get_json() if request.is_json else request.form.to_dict()
            
            # Validate required fields
            required_fields = ['rule_name', 'outlook_account_id', 'gmail_account_id']
            for field in required_fields:
                if not data.get(field):
                    return jsonify({'success': False, 'message': f'Missing required field: {field}'})
            
            # Parse filter criteria
            filter_criteria = None
            if data.get('filter_criteria'):
                if isinstance(data['filter_criteria'], str):
                    filter_criteria = json.loads(data['filter_criteria'])
                else:
                    filter_criteria = data['filter_criteria']
            
            # Validate criteria if provided
            if filter_criteria:
                valid, error_msg = rule_engine.validate_rule_criteria(filter_criteria)
                if not valid:
                    return jsonify({'success': False, 'message': f'Invalid filter criteria: {error_msg}'})
            
            # Create rule
            rule = ForwardingRule(
                rule_name=data['rule_name'],
                description=data.get('description'),
                outlook_account_id=int(data['outlook_account_id']),
                gmail_account_id=int(data['gmail_account_id']),
                filter_criteria=filter_criteria,
                priority=int(data.get('priority', 0)),
                add_prefix=data.get('add_prefix'),
                forward_attachments=data.get('forward_attachments', 'true').lower() == 'true',
                is_active=data.get('is_active', 'true').lower() == 'true'
            )
            
            db.session.add(rule)
            db.session.commit()
            
            if request.is_json:
                return jsonify({'success': True, 'rule_id': rule.id})
            else:
                flash(f'Created forwarding rule: {rule.rule_name}', 'success')
                return redirect(url_for('forwarding_rules'))
            
        except Exception as e:
            db.session.rollback()
            error_msg = f'Failed to create rule: {str(e)}'
            logger.error(error_msg)
            
            if request.is_json:
                return jsonify({'success': False, 'message': error_msg})
            else:
                flash(error_msg, 'error')
    
    # GET request - show form
    outlook_accounts = OutlookAccount.query.filter_by(is_active=True).all()
    gmail_accounts = GmailAccount.query.filter_by(is_active=True).all()
    
    return render_template('create_forwarding_rule.html',
        outlook_accounts=outlook_accounts,
        gmail_accounts=gmail_accounts
    )

@app.route('/forwarding-rules/<int:rule_id>/edit', methods=['GET', 'POST'])
# @login_required
def edit_forwarding_rule(rule_id):
    """Edit forwarding rule"""
    rule = ForwardingRule.query.get_or_404(rule_id)
    
    if request.method == 'POST':
        try:
            data = request.get_json() if request.is_json else request.form.to_dict()
            
            # Update rule fields
            if data.get('rule_name'):
                rule.rule_name = data['rule_name']
            if data.get('description') is not None:
                rule.description = data['description']
            if data.get('outlook_account_id'):
                rule.outlook_account_id = int(data['outlook_account_id'])
            if data.get('gmail_account_id'):
                rule.gmail_account_id = int(data['gmail_account_id'])
            if data.get('priority') is not None:
                rule.priority = int(data['priority'])
            if data.get('add_prefix') is not None:
                rule.add_prefix = data['add_prefix']
            if data.get('forward_attachments') is not None:
                rule.forward_attachments = data['forward_attachments'].lower() == 'true'
            if data.get('is_active') is not None:
                rule.is_active = data['is_active'].lower() == 'true'
            
            # Update filter criteria
            if 'filter_criteria' in data:
                filter_criteria = data['filter_criteria']
                if isinstance(filter_criteria, str):
                    filter_criteria = json.loads(filter_criteria) if filter_criteria else None
                
                if filter_criteria:
                    valid, error_msg = rule_engine.validate_rule_criteria(filter_criteria)
                    if not valid:
                        return jsonify({'success': False, 'message': f'Invalid filter criteria: {error_msg}'})
                
                rule.filter_criteria = filter_criteria
            
            rule.updated_at = datetime.utcnow()
            db.session.commit()
            
            if request.is_json:
                return jsonify({'success': True})
            else:
                flash(f'Updated forwarding rule: {rule.rule_name}', 'success')
                return redirect(url_for('forwarding_rules'))
            
        except Exception as e:
            db.session.rollback()
            error_msg = f'Failed to update rule: {str(e)}'
            logger.error(error_msg)
            
            if request.is_json:
                return jsonify({'success': False, 'message': error_msg})
            else:
                flash(error_msg, 'error')
    
    # GET request - show form
    outlook_accounts = OutlookAccount.query.filter_by(is_active=True).all()
    gmail_accounts = GmailAccount.query.filter_by(is_active=True).all()
    
    return render_template('edit_forwarding_rule.html',
        rule=rule,
        outlook_accounts=outlook_accounts,
        gmail_accounts=gmail_accounts
    )

@app.route('/api/forwarding-rules/<int:rule_id>/test', methods=['POST'])
# @login_required
def test_forwarding_rule(rule_id):
    """Test forwarding rule with sample email data"""
    rule = ForwardingRule.query.get_or_404(rule_id)
    
    try:
        # Get sample email data from request
        sample_data = request.get_json() or {}
        
        # Use default sample if none provided
        if not sample_data:
            sample_data = {
                'subject': 'Test Email Subject',
                'from': {
                    'emailAddress': {
                        'address': 'test@example.com',
                        'name': 'Test Sender'
                    }
                },
                'body': {
                    'content': 'This is a test email body',
                    'contentType': 'text'
                },
                'hasAttachments': False,
                'importance': 'normal',
                'receivedDateTime': datetime.utcnow().isoformat() + 'Z'
            }
        
        # Initialize enhanced forwarder for testing
        enhanced_forwarder = EnhancedEmailForwarder(microsoft_auth)
        result = enhanced_forwarder.test_forwarding_rule(rule, sample_data)
        
        return jsonify({
            'success': True,
            'result': result
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        })

@app.route('/api/forwarding-rules/<int:rule_id>/toggle', methods=['POST'])
# @login_required
def toggle_forwarding_rule(rule_id):
    """Toggle forwarding rule active status"""
    rule = ForwardingRule.query.get_or_404(rule_id)
    
    try:
        rule.is_active = not rule.is_active
        rule.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'is_active': rule.is_active
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e)
        })

@app.route('/api/forwarding-rules/<int:rule_id>/delete', methods=['DELETE'])
# @login_required
def delete_forwarding_rule(rule_id):
    """Delete forwarding rule"""
    rule = ForwardingRule.query.get_or_404(rule_id)
    
    try:
        rule_name = rule.rule_name
        db.session.delete(rule)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Deleted rule: {rule_name}'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e)
        })

@app.route('/api/forward/trigger', methods=['POST'])
# @login_required
def trigger_forward():
    """Manually trigger forwarding using enhanced forwarder"""
    try:
        use_enhanced = app.config.get('USE_ENHANCED_FORWARDER', True)
        
        if use_enhanced:
            # Use enhanced forwarder with rules
            thread = scheduler.trigger_manual_job(use_enhanced=True)
        else:
            # Use legacy forwarder
            thread = scheduler.trigger_manual_job(use_enhanced=False)
        
        return jsonify({
            'success': True,
            'message': 'Forwarding job started',
            'enhanced': use_enhanced
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        })

@app.route('/api/scheduler/pause', methods=['POST'])
# @login_required
def pause_scheduler():
    """Pause scheduler"""
    try:
        scheduler.pause_scheduler()
        status = scheduler.get_status()
        return jsonify({'success': True, 'status': status})
    except Exception as e:
        logger.error(f"Error pausing scheduler: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/scheduler/resume', methods=['POST'])
# @login_required
def resume_scheduler():
    """Resume scheduler"""
    try:
        scheduler.resume_scheduler()
        status = scheduler.get_status()
        return jsonify({'success': True, 'status': status})
    except Exception as e:
        logger.error(f"Error resuming scheduler: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/scheduler/toggle', methods=['POST'])
# @login_required
def toggle_scheduler():
    """Toggle scheduler pause/resume state"""
    try:
        status = scheduler.get_status()
        if status.get('is_paused', False):
            scheduler.resume_scheduler()
            action = 'resumed'
        else:
            scheduler.pause_scheduler()
            action = 'paused'
        
        new_status = scheduler.get_status()
        return jsonify({
            'success': True, 
            'action': action,
            'status': new_status
        })
    except Exception as e:
        logger.error(f"Error toggling scheduler: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/scheduler/update', methods=['POST'])
# @login_required
def update_scheduler():
    """Update scheduler interval"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'}), 400
        
        minutes = data.get('minutes')
        if not minutes:
            return jsonify({'success': False, 'message': 'Minutes parameter is required'}), 400
        
        try:
            minutes = int(minutes)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'Minutes must be a valid number'}), 400
        
        if minutes < 1:
            return jsonify({'success': False, 'message': 'Interval must be at least 1 minute'}), 400
        
        if minutes > 10080:  # 1 week
            return jsonify({'success': False, 'message': 'Interval cannot exceed 1 week (10080 minutes)'}), 400
        
        # Update the scheduler
        success = scheduler.update_interval(minutes)
        
        if success:
            logger.info(f"Scheduler interval updated to {minutes} minutes via API")
            return jsonify({
                'success': True, 
                'message': f'Interval updated to {minutes} minutes',
                'interval_minutes': minutes
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to update scheduler interval'}), 500
            
    except Exception as e:
        logger.error(f"Error updating scheduler interval: {str(e)}")
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500

@app.route('/api/scheduler/status')
# @login_required
def get_scheduler_status():
    """Get current scheduler status"""
    try:
        status = scheduler.get_status()
        return jsonify({'success': True, 'status': status})
    except Exception as e:
        logger.error(f"Error getting scheduler status: {str(e)}")
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500

@app.route('/settings')
# @login_required
def settings():
    """Settings page"""
    return render_template('settings.html', config=app.config)

@app.route('/api/stats')
# @login_required
def stats():
    """Get statistics for dashboard"""
    # Get forwarding stats for last 7 days
    from datetime import timedelta
    from sqlalchemy import func
    
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=7)
    
    daily_stats = db.session.query(
        func.date(ForwardingHistory.forwarded_at).label('date'),
        func.count(ForwardingHistory.id).label('count')
    ).filter(
        ForwardingHistory.forwarded_at >= start_date,
        ForwardingHistory.status == 'success'
    ).group_by(func.date(ForwardingHistory.forwarded_at)).all()
    
    return jsonify({
        'daily_stats': [{'date': str(stat.date), 'count': stat.count} for stat in daily_stats]
    })

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001) 