# Outlook to Gmail Forwarder

A comprehensive Python solution for forwarding Outlook emails to specific Gmail accounts based on customizable rules. This solution supports up to 1,000 emails at a time with automated forwarding at set intervals and flexible rule-based routing.

## Features

### Core Functionality
- ✅ **Multi-Account Support**: Forward from multiple Outlook 365 accounts to multiple Gmail accounts
- ✅ **Rule-Based Forwarding**: Create sophisticated rules to route emails to specific Gmail accounts
- ✅ **Automated Scheduling**: Set interval-based forwarding with manual trigger options
- ✅ **Bulk Processing**: Handle up to 1,000 emails per run with efficient batch processing
- ✅ **Account Monitoring**: Track which accounts are not forwarding with detailed error reporting
- ✅ **Easy Integration**: Import/export accounts via CSV with bulk management
- ✅ **Portable**: Move between servers easily with Docker support
- ✅ **Web UI**: Modern Flask-based interface for easy management
- ✅ **CLI Tools**: Command-line interface for automation and scripting

### Advanced Features
- 📧 **Smart Routing**: Route emails based on subject, sender, domain, attachments, and more
- 🔄 **Token Management**: Automatic OAuth token refresh for both Outlook and Gmail
- 📊 **Analytics**: Detailed forwarding history and statistics
- 🛡️ **Security**: Encrypted token storage with configurable encryption keys
- 🔍 **Testing**: Built-in rule testing and account connectivity verification
- 📱 **Responsive UI**: Mobile-friendly web interface
- 🐳 **Docker Support**: Containerized deployment for easy portability

## Quick Start

### Prerequisites
- Python 3.8+
- Microsoft Azure App Registration (for Outlook API)
- Google Cloud Project with Gmail API enabled

### Installation

1. **Clone the repository**
```bash
git clone <repository-url>
cd outlook2gmail
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Set up environment variables**
```bash
cp .env.example .env
# Edit .env with your configuration
```

4. **Initialize the database**
```bash
python cli.py init-db
```

5. **Start the application**
```bash
python app.py
```

## Configuration

### Environment Variables

Create a `.env` file with the following configuration:

```env
# Flask Configuration
FLASK_ENV=development
SECRET_KEY=your-secret-key-here
APP_URL=http://localhost:5000

# Database
DATABASE_URL=sqlite:///outlook2gmail.db

# Microsoft OAuth (Outlook)
MICROSOFT_CLIENT_ID=your-outlook-client-id
MICROSOFT_CLIENT_SECRET=your-outlook-client-secret
MICROSOFT_TENANT_ID=common

# Gmail OAuth (for multiple accounts)
GMAIL_CLIENT_ID=your-gmail-client-id
GMAIL_CLIENT_SECRET=your-gmail-client-secret

# Legacy Gmail API (for single account)
GMAIL_CREDENTIALS_FILE=config/gmail_credentials.json
GMAIL_TARGET_EMAIL=legacy-target@gmail.com

# Forwarding Settings
BATCH_SIZE=100
MAX_EMAILS_PER_RUN=1000
FORWARD_INTERVAL_MINUTES=30
USE_ENHANCED_FORWARDER=true

# Optional Redis Configuration
REDIS_URL=redis://localhost:6379/0
```

### OAuth Setup

#### Microsoft (Outlook) Setup
1. Go to [Azure Portal](https://portal.azure.com)
2. Register a new application
3. Add redirect URI: `http://localhost:5000/auth/callback`
4. Grant permissions: `Mail.Read`, `Mail.Send`, `offline_access`
5. Copy Client ID and Secret to `.env`

#### Gmail Setup
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Enable Gmail API
3. Create OAuth 2.0 credentials
4. Add redirect URI: `http://localhost:5000/gmail/callback`
5. Download credentials JSON and save as `config/gmail_credentials.json`
6. Copy Client ID and Secret to `.env`

## Usage

### Web Interface

1. **Access the dashboard**: http://localhost:5000
2. **Add Outlook accounts**: Navigate to Accounts → Add Account
3. **Add Gmail accounts**: Navigate to Gmail Accounts → Add Gmail Account
4. **Create forwarding rules**: Navigate to Forwarding Rules → Create Rule
5. **Monitor forwarding**: Check dashboard for statistics and job status

### Command Line Interface

#### Account Management
```bash
# List Outlook accounts
python cli.py list-accounts

# List Gmail accounts
python cli.py gmail list

# Test account connections
python cli.py test-account 1
python cli.py gmail test 1

# Import accounts from CSV
python cli.py import-accounts --csv-file accounts.csv
```

#### Forwarding Rules
```bash
# List all rules
python cli.py rules list

# Create a new rule
python cli.py rules create \
  --rule-name "Important Emails" \
  --outlook-account-id 1 \
  --gmail-account-id 1 \
  --criteria-file rule_criteria.json

# Test a rule
python cli.py rules test 1

# Create sample rule criteria
python cli.py create-sample-rule
```

#### Manual Forwarding
```bash
# Forward with rules (recommended)
python cli.py forward-now --use-rules --max-emails 100

# Legacy forwarding (single Gmail target)
python cli.py forward-now --max-emails 100

# Forward specific account
python cli.py forward-now --account-id 1 --use-rules
```

## Forwarding Rules

Create sophisticated rules to route emails to specific Gmail accounts based on various criteria.

### Rule Criteria Examples

**Simple rule** - Forward all emails from a specific domain:
```json
{
  "field": "sender_domain",
  "operator": "equals",
  "value": "company.com"
}
```

**Complex rule** - Forward important emails from specific senders:
```json
{
  "and": [
    {
      "field": "importance",
      "operator": "equals",
      "value": "high"
    },
    {
      "field": "sender_domain",
      "operator": "in_list",
      "value": ["company.com", "partner.com"]
    }
  ]
}
```

**Advanced rule** - Forward emails with attachments containing specific keywords:
```json
{
  "and": [
    {
      "field": "has_attachments",
      "operator": "equals",
      "value": true
    },
    {
      "or": [
        {
          "field": "subject",
          "operator": "contains",
          "value": "invoice"
        },
        {
          "field": "subject",
          "operator": "contains",
          "value": "receipt"
        }
      ]
    }
  ]
}
```

### Available Fields
- `subject` - Email subject line
- `sender` - Sender email address
- `sender_name` - Sender display name
- `sender_domain` - Sender's email domain
- `body` - Email body content
- `has_attachments` - Boolean for attachment presence
- `importance` - Email importance (low, normal, high)
- `received_date` - When email was received
- `to_recipients` - To recipients list
- `cc_recipients` - CC recipients list

### Available Operators
- `equals` - Exact match (case insensitive)
- `contains` - Contains substring (case insensitive)
- `starts_with` - Starts with string (case insensitive)
- `ends_with` - Ends with string (case insensitive)
- `regex` - Regular expression match
- `in_list` - Value in comma-separated list
- `greater_than` - Numeric comparison
- `less_than` - Numeric comparison
- `date_after` - Date comparison
- `date_before` - Date comparison

## CSV Import/Export

### Account Import Format
```csv
username,password,full_name,recovery_email,birthday,proxy_host,proxy_port,proxy_username,proxy_password
user1@outlook.com,password123,John Doe,recovery@email.com,1990-01-01,proxy.server.com,8080,proxyuser,proxypass
user2@outlook.com,password456,Jane Smith,jane.recovery@email.com,1985-05-15,,,
```

### Export Accounts
```bash
# Export without sensitive data
python cli.py export-accounts --output accounts_export.csv

# Export with tokens (be careful with security)
python cli.py export-accounts --output accounts_full.csv --include-tokens
```

## Docker Deployment

### Using Docker Compose

1. **Create docker-compose.yml**:
```yaml
version: '3.8'
services:
  outlook2gmail:
    build: .
    ports:
      - "5000:5000"
    environment:
      - FLASK_ENV=production
      - DATABASE_URL=sqlite:///data/outlook2gmail.db
    volumes:
      - ./data:/app/data
      - ./config:/app/config
      - ./logs:/app/logs
    restart: unless-stopped

  redis:
    image: redis:alpine
    ports:
      - "6379:6379"
    restart: unless-stopped
```

2. **Deploy**:
```bash
docker-compose up -d
```

### Standalone Docker
```bash
# Build image
docker build -t outlook2gmail .

# Run container
docker run -d \
  -p 5000:5000 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/config:/app/config \
  -v $(pwd)/logs:/app/logs \
  --env-file .env \
  outlook2gmail
```

## Monitoring and Troubleshooting

### Account Status
- Check the dashboard for account status indicators
- Red badges indicate accounts with errors
- Use the "Test" button to verify connectivity

### Common Issues

**Token Expired**
- Symptoms: 401 errors in logs
- Solution: Re-authenticate accounts through web UI

**Rate Limiting**
- Symptoms: 429 errors in logs
- Solution: Reduce batch size or increase interval

**No Matching Rules**
- Symptoms: Emails not being forwarded
- Solution: Check rule criteria and create default rules

### Logs
```bash
# View application logs
tail -f logs/app.log

# View forwarding job logs
python cli.py jobs
```

## API Reference

### REST Endpoints

#### Outlook Accounts
- `GET /accounts` - List accounts
- `GET /accounts/{id}` - Account details
- `POST /api/accounts/{id}/toggle` - Toggle account status
- `POST /api/accounts/{id}/test` - Test account connection

#### Gmail Accounts
- `GET /gmail-accounts` - List Gmail accounts
- `GET /gmail-accounts/{id}` - Gmail account details
- `POST /api/gmail-accounts/{id}/toggle` - Toggle Gmail account status
- `POST /api/gmail-accounts/{id}/test` - Test Gmail account connection

#### Forwarding Rules
- `GET /forwarding-rules` - List rules
- `POST /forwarding-rules/create` - Create rule
- `PUT /forwarding-rules/{id}/edit` - Update rule
- `DELETE /api/forwarding-rules/{id}/delete` - Delete rule
- `POST /api/forwarding-rules/{id}/test` - Test rule

#### Jobs
- `GET /jobs` - List forwarding jobs
- `POST /api/forward/trigger` - Trigger manual forwarding

## Development

### Setting up Development Environment

1. **Create virtual environment**:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. **Install development dependencies**:
```bash
pip install -r requirements.txt
pip install pytest pytest-cov black flake8
```

3. **Run tests**:
```bash
python -m pytest tests/
```

4. **Code formatting**:
```bash
black src/ cli.py app.py
flake8 src/ cli.py app.py
```

### Project Structure
```
outlook2gmail/
├── app.py                 # Flask web application
├── cli.py                 # Command-line interface
├── requirements.txt       # Python dependencies
├── Dockerfile            # Docker configuration
├── config/               # Configuration files
│   ├── config.py         # Application configuration
│   └── gmail_credentials.json
├── src/                  # Source code
│   ├── models.py         # Database models
│   ├── microsoft_auth.py # Outlook OAuth handling
│   ├── gmail_service.py  # Gmail API service
│   ├── email_forwarder.py # Legacy email forwarder
│   ├── enhanced_email_forwarder.py # Rule-based forwarder
│   ├── forwarding_rule_engine.py  # Rule evaluation engine
│   ├── csv_importer.py   # CSV import/export
│   └── scheduler.py      # Job scheduling
├── templates/            # HTML templates
├── static/              # Static assets
├── tests/               # Test files
├── logs/                # Application logs
└── uploads/             # File uploads
```

## Security Considerations

### Token Security
- All OAuth tokens are encrypted before storage
- Encryption keys are automatically generated and stored securely
- Never expose refresh tokens in logs or exports

### Network Security
- Use HTTPS in production
- Configure proper firewall rules
- Consider VPN for server access

### Access Control
- Change default admin credentials
- Use strong passwords
- Implement additional authentication if needed

## Performance Optimization

### Large Scale Deployments
- Use PostgreSQL or MySQL instead of SQLite for better performance
- Configure Redis for session storage and caching
- Use Celery for background job processing
- Set up load balancing for multiple instances

### Batch Processing
- Adjust `BATCH_SIZE` based on your server capacity
- Monitor memory usage during large email processing
- Use `MAX_EMAILS_PER_RUN` to limit job duration

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For issues, questions, or contributions:
- Create an issue on GitHub
- Check the troubleshooting section
- Review the logs for detailed error information

---

**Note**: This application handles sensitive email data. Always ensure proper security measures are in place when deploying to production environments. 