from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
import logging
import json
import os
from .models import OutlookAccount, ForwardingJob, db
from .email_forwarder import EmailForwarder
from .enhanced_email_forwarder import EnhancedEmailForwarder
from .microsoft_auth import MicrosoftAuth
from flask import current_app
import threading

logger = logging.getLogger(__name__)

class ForwardingScheduler:
    """Scheduler for automated email forwarding"""
    
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.is_running = False
        self.is_paused = False  # Track paused state explicitly
        self.current_job = None
        self.lock = threading.Lock()
        self.app = None
        self.current_interval_minutes = 30  # Default interval

        
    def init_app(self, app):
        """Initialize scheduler with Flask app"""
        self.app = app
        
        # Load persisted state
        self._load_state()
        
        # Start scheduler
        self.scheduler.start()
        
        # Add scheduled job
        interval_minutes = self.current_interval_minutes or app.config.get('FORWARD_INTERVAL_MINUTES', 30)
        self.current_interval_minutes = interval_minutes
        use_enhanced = app.config.get('USE_ENHANCED_FORWARDER', True)
        
        self.scheduler.add_job(
            func=lambda: self.run_forwarding_job('scheduled', use_enhanced),
            trigger=IntervalTrigger(minutes=interval_minutes),
            id='forward_emails',
            name='Forward emails from Outlook to Gmail',
            replace_existing=True
        )
        
        # Apply paused state if it was persisted
        if self.is_paused:
            self.scheduler.pause()
            logger.info(f"Scheduler restored to paused state")
        
        logger.info(f"Scheduler initialized with {interval_minutes} minute interval, enhanced={use_enhanced}, paused={self.is_paused}")

    
    def run_forwarding_job(self, job_type='scheduled', use_enhanced=None):
        """Run email forwarding for all active accounts"""
        with self.lock:
            if self.is_running:
                logger.warning("Forwarding job already running, skipping")
                return
            
            self.is_running = True

        try:
            with self.app.app_context():
                logger.info(f"Starting {job_type} forwarding job")
                
                # Determine which forwarder to use
                if use_enhanced is None:
                    use_enhanced = self.app.config.get('USE_ENHANCED_FORWARDER', True)
                
                # Create job record
                job = ForwardingJob(
                    job_type=job_type,
                    status='running',
                    started_at=datetime.utcnow()
                )
                db.session.add(job)
                db.session.commit()
                self.current_job = job
                
                # Get active accounts
                active_accounts = OutlookAccount.query.filter_by(is_active=True).all()
                job.total_accounts = len(active_accounts)
                
                if not active_accounts:
                    logger.info("No active accounts found")
                    job.status = 'completed'
                    job.completed_at = datetime.utcnow()
                    db.session.commit()
                    return
                
                # Initialize appropriate forwarder
                microsoft_auth = MicrosoftAuth(
                    self.app.config['MICROSOFT_CLIENT_ID'],
                    self.app.config['MICROSOFT_CLIENT_SECRET']
                )
                
                if use_enhanced:
                    logger.info("Using enhanced email forwarder with rules")
                    forwarder = EnhancedEmailForwarder(microsoft_auth)
                else:
                    logger.info("Using legacy email forwarder with Gmail API")
                    forwarder = EmailForwarder(
                        microsoft_auth,
                        self.app.config.get('GMAIL_CREDENTIALS_FILE', 'config/gmail_credentials.json'),
                        self.app.config.get('GMAIL_TARGET_EMAIL', '')
                    )
                    
                    if not forwarder.initialize_gmail_service():
                        raise Exception("Failed to initialize Gmail API service")
                
                logger.info(f"Processing {len(active_accounts)} active accounts")
                
                total_success = 0
                total_failed = 0
                job_errors = []
                
                # Process each account
                for account in active_accounts:
                    try:
                        logger.info(f"Processing account: {account.email or account.username}")
                        
                        # Forward emails
                        result = forwarder.forward_emails(
                            account, 
                            db,
                            max_emails=self.app.config['MAX_EMAILS_PER_RUN']
                        )
                        
                        total_success += result['success']
                        total_failed += result['failed']
                        
                        if result['errors']:
                            job_errors.append({
                                'account': account.email or account.username,
                                'errors': result['errors'][:5]  # Limit errors per account
                            })
                        
                        # Log rule usage for enhanced forwarder
                        if use_enhanced and result.get('processed_rules'):
                            logger.info(f"Rules used for {account.email}:")
                            for rule_info in result['processed_rules'].values():
                                logger.info(f"  - {rule_info['rule_name']}: {rule_info['count']} emails -> {rule_info['gmail_account']}")
                        
                        job.processed_accounts += 1
                        
                        # Update job progress
                        if job.processed_accounts % 10 == 0:
                            job.forwarded_emails = total_success
                            job.failed_emails = total_failed
                            db.session.commit()
                        
                    except Exception as e:
                        logger.error(f"Error processing account {account.email or account.username}: {str(e)}")
                        job_errors.append({
                            'account': account.email or account.username,
                            'errors': [str(e)]
                        })
                
                # Update job completion
                job.status = 'completed'
                job.completed_at = datetime.utcnow()
                job.forwarded_emails = total_success
                job.failed_emails = total_failed
                job.errors = job_errors if job_errors else None
                
                db.session.commit()
                
                logger.info(f"Forwarding job completed: {total_success} forwarded, {total_failed} failed")
                
        except Exception as e:
            logger.error(f"Forwarding job failed: {str(e)}")
            
            try:
                with self.app.app_context():
                    if self.current_job:
                        self.current_job.status = 'failed'
                        self.current_job.completed_at = datetime.utcnow()
                        self.current_job.errors = [{'error': str(e)}]
                        db.session.commit()
            except:
                pass
                
        finally:
            self.is_running = False
            self.current_job = None
    
    def trigger_manual_job(self, use_enhanced=None):
        """Trigger a manual forwarding job"""
        if self.is_running:
            raise Exception("Forwarding job already running")
        
        # Run in background thread
        thread = threading.Thread(
            target=self.run_forwarding_job,
            args=('manual', use_enhanced)
        )
        thread.daemon = True
        thread.start()
        return thread
    
    def _get_state_file_path(self):
        """Get the path to the scheduler state file"""
        return os.path.join('config', 'scheduler_state.json')
    
    def _load_state(self):
        """Load persisted scheduler state"""
        try:
            state_file = self._get_state_file_path()
            if os.path.exists(state_file):
                with open(state_file, 'r') as f:
                    state = json.load(f)
                    self.is_paused = state.get('is_paused', False)
                    self.current_interval_minutes = state.get('interval_minutes', 30)
                    logger.info(f"Loaded scheduler state: paused={self.is_paused}, interval={self.current_interval_minutes}")
            else:
                logger.info("No persisted scheduler state found, using defaults")
        except Exception as e:
            logger.error(f"Error loading scheduler state: {str(e)}")
    
    def _save_state(self):
        """Save scheduler state to persist across restarts"""
        try:
            state = {
                'is_paused': self.is_paused,
                'interval_minutes': self.current_interval_minutes,
                'last_updated': datetime.utcnow().isoformat()
            }
            
            state_file = self._get_state_file_path()
            os.makedirs(os.path.dirname(state_file), exist_ok=True)
            
            with open(state_file, 'w') as f:
                json.dump(state, f, indent=2)
            
            logger.debug(f"Saved scheduler state: {state}")
        except Exception as e:
            logger.error(f"Error saving scheduler state: {str(e)}")
    
    def pause_scheduler(self):
        """Pause the scheduler"""
        self.scheduler.pause()
        self.is_paused = True
        self._save_state()  # Persist the state
        logger.info("Scheduler paused")
    
    def resume_scheduler(self):
        """Resume the scheduler"""
        self.scheduler.resume()
        self.is_paused = False
        self._save_state()  # Persist the state
        logger.info("Scheduler resumed")
    
    def update_interval(self, minutes):
        """Update forwarding interval"""
        try:
            if minutes < 1:
                raise ValueError("Interval must be at least 1 minute")
            
            self.current_interval_minutes = minutes
            
            # Get the current job configuration
            current_job = self.scheduler.get_job('forward_emails')
            if not current_job:
                logger.error("Forward emails job not found")
                return False
            
            # Update the job trigger
            self.scheduler.reschedule_job(
                job_id='forward_emails',
                trigger=IntervalTrigger(minutes=minutes)
            )
            
            # Update the app config if app is available
            if self.app:
                with self.app.app_context():
                    self.app.config['FORWARD_INTERVAL_MINUTES'] = minutes
            
            # Save the updated state
            self._save_state()
            
            logger.info(f"Scheduler interval updated to {minutes} minutes")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update scheduler interval: {str(e)}")
            return False
    
    def get_status(self):
        """Get scheduler status"""
        try:
            job = self.scheduler.get_job('forward_emails')
            next_run_time = job.next_run_time if job else None
            
            # Determine if scheduler is truly paused
            # APScheduler state: 0=stopped, 1=running, 2=paused
            scheduler_state = self.scheduler.state
            actual_paused = (scheduler_state == 2) or self.is_paused
            
            return {
                'running': self.scheduler.running,
                'is_paused': actual_paused,
                'job_running': self.is_running,
                'current_job_id': self.current_job.id if self.current_job else None,
                'interval_minutes': self.current_interval_minutes,
                'next_run_time': next_run_time.isoformat() if next_run_time else None,
                'job_exists': job is not None,
                'scheduler_state': self.scheduler.state.name if hasattr(self.scheduler.state, 'name') else str(self.scheduler.state)
            }
        except Exception as e:
            logger.error(f"Error getting scheduler status: {str(e)}")
            return {
                'running': False,
                'is_paused': self.is_paused,
                'job_running': self.is_running,
                'current_job_id': None,
                'interval_minutes': self.current_interval_minutes,
                'next_run_time': None,
                'job_exists': False,
                'error': str(e)
            } 