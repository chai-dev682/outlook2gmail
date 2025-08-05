# Outlook to Gmail Forwarder

A comprehensive Python application that automatically forwards emails from multiple Outlook accounts to a single Gmail workspace account. Features include automated scheduling, web UI, CLI interface, and support for up to 1,000 emails per forwarding run.

## Features

- ✅ **Bulk Email Forwarding**: Forward up to 1,000 emails at a time
- ✅ **Automated Scheduling**: Set intervals for automatic forwarding
- ✅ **Web Interface**: Modern Flask-based UI with real-time monitoring
- ✅ **CLI Support**: Full command-line interface for automation
- ✅ **CSV Import/Export**: Bulk account management
- ✅ **OAuth2 Authentication**: Secure token-based authentication
- ✅ **Proxy Support**: Per-account proxy configuration
- ✅ **Error Tracking**: Comprehensive error logging and monitoring
- ✅ **Portable**: Easy server migration with encrypted credentials

## Prerequisites

- Python 3.8 or higher
- Gmail Workspace account
- Microsoft Azure App registration
- SQLite (included) or PostgreSQL/MySQL

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/outlook2gmail.git
cd outlook2gmail
```

2. Create virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Initialize database:
```bash
python cli.py init-db
```

5. Create environment configuration:
```bash
python cli.py create-env
cp .env.example .env
```

## Configuration

### Microsoft Azure Setup

1. Register an application in Azure Portal
2. Add the following API permissions:
   - Microsoft Graph: Mail.Read
   - Microsoft Graph: Mail.Send
   - Microsoft Graph: offline_access
3. Create a client secret
4. Update `.env` with your credentials:

```env
MICROSOFT_CLIENT_ID=your-client-id
MICROSOFT_CLIENT_SECRET=your-client-secret
```

### Gmail API Setup

1. Enable Gmail API in Google Cloud Console
2. Create OAuth2 credentials
3. Download credentials as `gmail_credentials.json`
4. Place in `config/` directory
5. Update `.env`:

```env
GMAIL_TARGET_EMAIL=target@yourdomain.com
GMAIL_CREDENTIALS_FILE=config/gmail_credentials.json
```

### Environment Variables

```env
# Flask Configuration
FLASK_ENV=production
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
```

## Usage

### Web Interface

1. Start the Flask application:
```bash
python app.py
```

2. Access the web interface at `http://localhost:5000`
3. Login with default credentials:
   - Username: `admin`
   - Password: `admin123`

### CLI Usage

#### Import accounts from CSV:
```bash
python cli.py import-accounts --csv-file accounts.csv
```

#### List all accounts:
```bash
python cli.py list-accounts --active-only
```

#### Manual forwarding:
```bash
python cli.py forward-now --max-emails 100
```

#### View statistics:
```bash
python cli.py stats
```

#### Test specific account:
```bash
python cli.py test-account 1
```

### CSV Import Format

The CSV file should contain these columns:
- **Provider**: Must be "Outlook"
- **Username**: Outlook email address
- **OAuth2 Refresh Token**: Refresh token for authentication
- **Full Name**: Account owner name (optional)
- **Recovery Email**: Recovery email (optional)
- **Birthday**: Birthday (optional)
- **Browser Proxy**: Format: `host:port:username:password` (optional)

Example CSV:
```csv
Provider,Username,OAuth2 Refresh Token,Full Name
Outlook,user@outlook.com,M.C516_SN1...,John Doe
```

## API Endpoints

### Account Management
- `GET /api/accounts` - List all accounts
- `POST /api/accounts/<id>/toggle` - Enable/disable account
- `POST /api/accounts/<id>/test` - Test account connection

### Forwarding Control
- `POST /api/forward/trigger` - Manually trigger forwarding
- `POST /api/scheduler/pause` - Pause automatic forwarding
- `POST /api/scheduler/resume` - Resume automatic forwarding
- `POST /api/scheduler/update` - Update forwarding interval

### Statistics
- `GET /api/stats` - Get forwarding statistics

## Testing

Run the test suite:
```bash
pytest tests/
```

Run with coverage:
```bash
pytest --cov=src tests/
```

## Deployment

### Using Gunicorn

```bash
gunicorn -w 4 -b 0.0.0.0:8000 app:app
```

### Using Docker

1. Build the image:
```bash
docker build -t outlook2gmail .
```

2. Run the container:
```bash
docker run -d -p 5000:5000 \
  -v $(pwd)/data:/app/data \
  -e DATABASE_URL=sqlite:///data/outlook2gmail.db \
  outlook2gmail
```

### Server Migration

1. Export accounts with tokens:
```bash
python cli.py export-accounts --output backup.csv --include-tokens
```

2. Copy the following to new server:
   - `backup.csv`
   - `config/encryption.key`
   - `config/gmail_credentials.json`
   - `.env` file

3. On new server:
```bash
python cli.py init-db
python cli.py import-accounts --csv-file backup.csv
```

## Security Considerations

- All tokens are encrypted using Fernet encryption
- HTTPS should be used in production
- Regular token rotation is recommended
- Use strong passwords for admin accounts
- Keep `config/encryption.key` secure

## Troubleshooting

### Common Issues

1. **Token Refresh Failures (AADSTS40008)**
   - **Error**: "External identity provider error"
   - **Causes**:
     - Temporary Microsoft service issues
     - Expired or revoked refresh token
     - Account security changes (password reset, 2FA changes)
   - **Solutions**:
     ```bash
     # Test specific account
     python cli.py test-account <account_id>
     
     # Check accounts with errors
     python cli.py reauth --all-failed
     
     # Re-authenticate specific account
     python cli.py reauth <account_id>
     
     # Update token manually
     python cli.py update-token <account_id> <new_refresh_token>
     ```

2. **Invalid or Expired Refresh Tokens**
   - Refresh tokens can expire after 90 days of inactivity
   - Security events (password changes) invalidate tokens
   - Solution: Re-authenticate through OAuth flow
   - The system will automatically deactivate accounts with invalid tokens

3. **Gmail API Errors**
   - Ensure Gmail API is enabled
   - Verify credentials file path
   - Check target email permissions
   - Run initial OAuth flow for Gmail service account

4. **High Error Counts**
   - Review account error messages in UI
   - Check logs in `logs/app.log`
   - Test individual accounts using CLI
   - Accounts with consecutive errors > 5 may need re-authentication

### Handling Token Refresh Errors

The application implements automatic retry logic for transient errors:
- **AADSTS40008**: Retries 3 times with exponential backoff
- **Invalid tokens**: Automatically deactivates the account
- **Network errors**: Retries with timeout handling

To bulk update tokens from a new CSV:
```bash
python cli.py import-accounts --csv-file updated_tokens.csv --update-only
```

### Logging

Logs are stored in:
- Application logs: `logs/app.log`
- Error details: Database `forwarding_history` table
- Account-specific errors: `outlook_accounts.last_error` field

Enable debug logging:
```bash
LOG_LEVEL=DEBUG python app.py
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For issues and questions:
- Create an issue on GitHub
- Check existing issues for solutions
- Review logs for error details 