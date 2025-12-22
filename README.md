# Telegram Bot - Psychological Card Reader

Django + aiogram Telegram bot that provides psychological/coaching card reading sessions.

## Quick Start with Docker Compose

### Prerequisites

- Docker & Docker Compose
- Environment variables configured

### Environment Variables

Create `.env` file or export variables:

```bash
SECRET_KEY=your-django-secret-key
TELEGRAM_BOT_TOKEN=your-bot-token
ALLOWED_HOSTS=your-domain.com,localhost
MASTER_NAME=your-telegram-username
DEBUG=False
```

### Run

```bash
# Build and start all services
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

### Services

- **nginx** - Reverse proxy (ports 80/443)
- **django** - Django admin & API (internal port 8000)
- **bot** - Telegram bot (polling mode)

### First Time Setup

```bash
# Migrations run automatically on container start via entrypoint.sh
# But you can run them manually if needed:
docker compose exec django python manage.py migrate

# Create superuser
docker compose exec django python manage.py createsuperuser

# Create subscription plans (runs automatically on deployment)
docker compose exec django python manage.py create_subscriptions
```

### Automatic Migrations

Migrations run automatically when Django container starts:
- Database migrations (`python manage.py migrate`)
- Subscription plans creation (`python manage.py create_subscriptions`)
- Static files collection (`python manage.py collectstatic`)

## Testing

### Run Tests

```bash
# Run all tests with coverage
pytest tests/ -v

# Run with coverage report
pytest tests/ -v --cov=bot --cov-report=html

# Run specific test file
pytest tests/test_models.py -v

# Run specific test class
pytest tests/test_models.py::TestTelegramProfile -v

# Run specific test
pytest tests/test_models.py::TestTelegramProfile::test_is_subscribed_free -v
```

### Test Coverage

Total: **66 tests** passing | **85% coverage**

Key modules coverage:
- `bot/services/prodamus_service.py` - 100% coverage
- `bot/models.py` - 89% coverage
- `bot/services/bot_storage.py` - 76% coverage
- `bot/admin.py` - 100% coverage
- `bot/views.py` - Fully tested (webhook + success page)

View detailed coverage report:
```bash
pytest tests/ --cov=bot --cov-report=html
open htmlcov/index.html
```

### Writing Tests

Tests are located in `tests/` directory:
- `test_models.py` - Model tests (TelegramProfile, Subscription, Payment, UserSession)
- `test_storage.py` - DjangoStorage async methods tests
- `test_prodamus_service.py` - ProdamusService integration tests (payment links, signatures, webhooks)
- `test_views.py` - Views tests (webhook handler, success page)
- `conftest.py` - Shared fixtures

Example test:
```python
import pytest
from bot.models import TelegramProfile

@pytest.mark.django_db
def test_example(telegram_profile):
    assert telegram_profile.is_subscribed is True
```

## CI/CD

GitHub Actions automatically runs tests and deploys on push to `master`.

**Deployment process:**
1. Run tests with migrations
2. Deploy to VPS via SSH
3. Pull latest code
4. Rebuild Docker containers
5. **Migrations run automatically** via entrypoint script
6. Restart services

**Required GitHub configuration:**
- **Secrets**: `SECRET_KEY`, `TELEGRAM_BOT_TOKEN`, `PRODAMUS_SECRET_KEY`, VPS credentials
- **Variables**: `ALLOWED_HOSTS`, `BASE_URL`, `PRODAMUS_MERCHANT_URL`, `PRODAMUS_TEST_MODE`
