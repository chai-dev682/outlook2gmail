from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy import JSON
import json

db = SQLAlchemy()

class OutlookAccount(db.Model):
    """Model for storing Outlook account information"""
    __tablename__ = 'outlook_accounts'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(255), unique=True, nullable=False)
    email = db.Column(db.String(255), nullable=True)  # Adding email field
    display_name = db.Column(db.String(255), nullable=True)  # Adding display name
    password = db.Column(db.String(255), nullable=True)  # Encrypted
    refresh_token = db.Column(db.Text, nullable=True)  # Encrypted
    access_token = db.Column(db.Text, nullable=True)  # Encrypted
    token_expires_at = db.Column(db.DateTime, nullable=True)
    
    # Account details
    full_name = db.Column(db.String(255), nullable=True)
    recovery_email = db.Column(db.String(255), nullable=True)
    birthday = db.Column(db.String(50), nullable=True)
    
    # Proxy settings
    proxy_host = db.Column(db.String(255), nullable=True)
    proxy_port = db.Column(db.Integer, nullable=True)
    proxy_username = db.Column(db.String(255), nullable=True)
    proxy_password = db.Column(db.String(255), nullable=True)
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    last_sync = db.Column(db.DateTime, nullable=True)
    last_error = db.Column(db.Text, nullable=True)
    consecutive_errors = db.Column(db.Integer, default=0)
    
    # Statistics
    total_emails_forwarded = db.Column(db.Integer, default=0)
    total_emails_failed = db.Column(db.Integer, default=0)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    forwarding_history = db.relationship('ForwardingHistory', backref='account', lazy='dynamic')
    forwarding_rules = db.relationship('ForwardingRule', backref='outlook_account', lazy='dynamic')
    
    def __repr__(self):
        return f'<OutlookAccount {self.username}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'display_name': self.display_name,
            'full_name': self.full_name,
            'is_active': self.is_active,
            'last_sync': self.last_sync.isoformat() if self.last_sync else None,
            'last_error': self.last_error,
            'consecutive_errors': self.consecutive_errors,
            'total_emails_forwarded': self.total_emails_forwarded,
            'total_emails_failed': self.total_emails_failed,
            'created_at': self.created_at.isoformat()
        }

class GmailAccount(db.Model):
    """Model for storing Gmail account information"""
    __tablename__ = 'gmail_accounts'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    display_name = db.Column(db.String(255), nullable=True)
    
    # OAuth credentials (encrypted)
    refresh_token = db.Column(db.Text, nullable=True)
    access_token = db.Column(db.Text, nullable=True)
    token_expires_at = db.Column(db.DateTime, nullable=True)
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    last_used = db.Column(db.DateTime, nullable=True)
    last_error = db.Column(db.Text, nullable=True)
    consecutive_errors = db.Column(db.Integer, default=0)
    
    # Statistics
    total_emails_received = db.Column(db.Integer, default=0)
    total_emails_failed = db.Column(db.Integer, default=0)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    forwarding_history = db.relationship('ForwardingHistory', backref='gmail_account', lazy='dynamic')
    forwarding_rules = db.relationship('ForwardingRule', backref='gmail_account', lazy='dynamic')
    
    def __repr__(self):
        return f'<GmailAccount {self.email}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'display_name': self.display_name,
            'is_active': self.is_active,
            'last_used': self.last_used.isoformat() if self.last_used else None,
            'last_error': self.last_error,
            'consecutive_errors': self.consecutive_errors,
            'total_emails_received': self.total_emails_received,
            'total_emails_failed': self.total_emails_failed,
            'created_at': self.created_at.isoformat()
        }

class ForwardingRule(db.Model):
    """Model for defining forwarding rules between Outlook and Gmail accounts"""
    __tablename__ = 'forwarding_rules'
    
    id = db.Column(db.Integer, primary_key=True)
    outlook_account_id = db.Column(db.Integer, db.ForeignKey('outlook_accounts.id'), nullable=False)
    gmail_account_id = db.Column(db.Integer, db.ForeignKey('gmail_accounts.id'), nullable=False)
    
    # Rule details
    rule_name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    
    # Filtering criteria (JSON stored as text)
    filter_criteria = db.Column(JSON, nullable=True)  # e.g., {"subject_contains": "important", "from_domain": "company.com"}
    
    # Rule settings
    is_active = db.Column(db.Boolean, default=True)
    priority = db.Column(db.Integer, default=0)  # Lower number = higher priority
    
    # Email modification settings
    add_prefix = db.Column(db.String(100), nullable=True)  # Prefix to add to subject
    forward_attachments = db.Column(db.Boolean, default=True)
    
    # Statistics
    emails_processed = db.Column(db.Integer, default=0)
    last_used = db.Column(db.DateTime, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<ForwardingRule {self.rule_name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'outlook_account_id': self.outlook_account_id,
            'gmail_account_id': self.gmail_account_id,
            'rule_name': self.rule_name,
            'description': self.description,
            'filter_criteria': self.filter_criteria,
            'is_active': self.is_active,
            'priority': self.priority,
            'add_prefix': self.add_prefix,
            'forward_attachments': self.forward_attachments,
            'emails_processed': self.emails_processed,
            'last_used': self.last_used.isoformat() if self.last_used else None,
            'created_at': self.created_at.isoformat()
        }

class ForwardingHistory(db.Model):
    """Model for tracking email forwarding history"""
    __tablename__ = 'forwarding_history'
    
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('outlook_accounts.id'), nullable=False)
    gmail_account_id = db.Column(db.Integer, db.ForeignKey('gmail_accounts.id'), nullable=True)
    rule_id = db.Column(db.Integer, db.ForeignKey('forwarding_rules.id'), nullable=True)
    
    # Email details
    outlook_message_id = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(500), nullable=True)
    sender = db.Column(db.String(255), nullable=True)
    received_date = db.Column(db.DateTime, nullable=True)
    
    # Forwarding details
    forwarded_at = db.Column(db.DateTime, default=datetime.utcnow)
    gmail_message_id = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(50), default='pending')  # pending, success, failed
    error_message = db.Column(db.Text, nullable=True)
    retry_count = db.Column(db.Integer, default=0)
    
    # Metadata
    email_size = db.Column(db.Integer, nullable=True)  # in bytes
    has_attachments = db.Column(db.Boolean, default=False)
    
    def __repr__(self):
        return f'<ForwardingHistory {self.outlook_message_id} -> {self.status}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'account_id': self.account_id,
            'gmail_account_id': self.gmail_account_id,
            'rule_id': self.rule_id,
            'outlook_message_id': self.outlook_message_id,
            'subject': self.subject,
            'sender': self.sender,
            'received_date': self.received_date.isoformat() if self.received_date else None,
            'forwarded_at': self.forwarded_at.isoformat(),
            'gmail_message_id': self.gmail_message_id,
            'status': self.status,
            'error_message': self.error_message,
            'retry_count': self.retry_count
        }

class ForwardingJob(db.Model):
    """Model for tracking forwarding jobs"""
    __tablename__ = 'forwarding_jobs'
    
    id = db.Column(db.Integer, primary_key=True)
    job_type = db.Column(db.String(50), nullable=False)  # scheduled, manual
    status = db.Column(db.String(50), default='pending')  # pending, running, completed, failed
    
    # Job details
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    # Statistics
    total_accounts = db.Column(db.Integer, default=0)
    processed_accounts = db.Column(db.Integer, default=0)
    total_emails = db.Column(db.Integer, default=0)
    forwarded_emails = db.Column(db.Integer, default=0)
    failed_emails = db.Column(db.Integer, default=0)
    
    # Error tracking
    errors = db.Column(JSON, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<ForwardingJob {self.id} - {self.status}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'job_type': self.job_type,
            'status': self.status,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'total_accounts': self.total_accounts,
            'processed_accounts': self.processed_accounts,
            'total_emails': self.total_emails,
            'forwarded_emails': self.forwarded_emails,
            'failed_emails': self.failed_emails,
            'errors': self.errors,
            'created_at': self.created_at.isoformat()
        }

class User(UserMixin, db.Model):
    """Admin user model for Flask-Login"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<User {self.username}>' 