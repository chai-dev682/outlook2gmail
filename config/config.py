import os
from datetime import timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    """Base configuration"""
    # Flask settings
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    DEBUG = False
    TESTING = False
    
    # Database settings
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///outlook2gmail.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Microsoft OAuth settings
    MICROSOFT_CLIENT_ID = os.environ.get('MICROSOFT_CLIENT_ID', '')
    MICROSOFT_CLIENT_SECRET = os.environ.get('MICROSOFT_CLIENT_SECRET', '')
    MICROSOFT_AUTHORITY = 'https://login.microsoftonline.com/common'
    MICROSOFT_REDIRECT_PATH = '/auth/callback'
    MICROSOFT_SCOPE = ['https://graph.microsoft.com/Mail.Read', 
                       'https://graph.microsoft.com/Mail.Send',
                       'offline_access']
    
    # Gmail API settings
    GMAIL_CREDENTIALS_FILE = os.environ.get('GMAIL_CREDENTIALS_FILE', 'config/gmail_credentials.json')
    GMAIL_TOKEN_FILE = os.environ.get('GMAIL_TOKEN_FILE', 'config/gmail_token.json')
    GMAIL_SCOPES = ['https://www.googleapis.com/auth/gmail.send']
    GMAIL_TARGET_EMAIL = os.environ.get('GMAIL_TARGET_EMAIL', '')
    
    # Email forwarding settings
    BATCH_SIZE = int(os.environ.get('BATCH_SIZE', 100))
    MAX_EMAILS_PER_RUN = int(os.environ.get('MAX_EMAILS_PER_RUN', 1000))
    FORWARD_INTERVAL_MINUTES = int(os.environ.get('FORWARD_INTERVAL_MINUTES', 30))
    
    # Redis/Celery settings (optional)
    REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', REDIS_URL)
    CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', REDIS_URL)
    
    # Rate limiting
    RATELIMIT_STORAGE_URL = os.environ.get('RATELIMIT_STORAGE_URL', 'memory://')
    
    # Session settings
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # Logging
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
    LOG_FILE = os.environ.get('LOG_FILE', 'logs/outlook2gmail.log')
    
    # Proxy settings (from CSV)
    USE_PROXY = os.environ.get('USE_PROXY', 'false').lower() == 'true'
    
class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    SESSION_COOKIE_SECURE = False
    
class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    
class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    
# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
} 