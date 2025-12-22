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
# Run migrations
docker compose exec django python manage.py migrate

# Create superuser
docker compose exec django python manage.py createsuperuser

# Collect static files
docker compose exec django python manage.py collectstatic --noinput
```

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

Current test coverage: **82.83%**

- `bot/models.py` - 86% coverage
- `bot/services/bot_storage.py` - 76% coverage

View detailed coverage report:
```bash
pytest tests/ --cov=bot --cov-report=html
open htmlcov/index.html
```

### Writing Tests

Tests are located in `tests/` directory:
- `test_models.py` - Model tests (TelegramProfile, Subscription, Payment, UserSession)
- `test_storage.py` - DjangoStorage async methods tests
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
