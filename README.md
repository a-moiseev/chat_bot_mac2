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

## CI/CD

GitHub Actions automatically runs tests and deploys on push to `master`.
