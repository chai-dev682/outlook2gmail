import os
import logging
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_file
from flask_migrate import Migrate
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import json

from config.config import config
from src.models import db, User, OutlookAccount, ForwardingHistory, ForwardingJob
from src.microsoft_auth import MicrosoftAuth
from src.email_forwarder import EmailForwarder
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

def initialize_services():
    """Initialize services"""
    global microsoft_auth, csv_importer
    
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
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# Main routes
@app.route('/')
@login_required
def dashboard():
    """Main dashboard"""
    # Get statistics
    total_accounts = OutlookAccount.query.count()
    active_accounts = OutlookAccount.query.filter_by(is_active=True).count()
    
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
    
    return render_template('dashboard.html',
        total_accounts=total_accounts,
        active_accounts=active_accounts,
        recent_forwards=recent_forwards,
        recent_jobs=recent_jobs,
        scheduler_status=scheduler_status
    )

@app.route('/accounts')
@login_required
def accounts():
    """Account management page"""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    accounts = OutlookAccount.query.paginate(
        page=page, 
        per_page=per_page,
        error_out=False
    )
    
    return render_template('accounts.html', accounts=accounts)

@app.route('/accounts/<int:account_id>')
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
def jobs():
    """View forwarding jobs"""
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    jobs = ForwardingJob.query.order_by(
        ForwardingJob.created_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template('jobs.html', jobs=jobs)

@app.route('/api/forward/trigger', methods=['POST'])
@login_required
def trigger_forward():
    """Manually trigger forwarding"""
    try:
        thread = scheduler.trigger_manual_job()
        return jsonify({
            'success': True,
            'message': 'Forwarding job started'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        })

@app.route('/api/scheduler/pause', methods=['POST'])
@login_required
def pause_scheduler():
    """Pause scheduler"""
    scheduler.pause_scheduler()
    return jsonify({'success': True})

@app.route('/api/scheduler/resume', methods=['POST'])
@login_required
def resume_scheduler():
    """Resume scheduler"""
    scheduler.resume_scheduler()
    return jsonify({'success': True})

@app.route('/api/scheduler/update', methods=['POST'])
@login_required
def update_scheduler():
    """Update scheduler interval"""
    minutes = request.json.get('minutes', 30)
    scheduler.update_interval(minutes)
    return jsonify({'success': True})

@app.route('/settings')
@login_required
def settings():
    """Settings page"""
    return render_template('settings.html', config=app.config)

@app.route('/api/stats')
@login_required
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