# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Code Style

- Comment only complex or non-obvious logic
- Do not use emojis in code, comments, or commit messages
- Keep code clean and self-documenting

## Project Overview

This is a Django-based Telegram bot (mac_bot_2) that provides psychological/coaching card reading sessions to users. The bot uses aiogram 3.0 for Telegram integration and Django for data persistence. Users receive a random card image (day/night variants) and are guided through a structured conversation to reflect on their request.

## Architecture

### Django + Aiogram Integration

This project uses an unusual but functional architecture that combines Django ORM with aiogram's async bot framework:

- **Django ORM for persistence**: All data (users, states, sessions) is stored via Django models
- **aiogram for bot logic**: Asynchronous Telegram bot using FSM (Finite State Machine) for conversation flow
- **Bridge layer**: `bot/services/bot_storage.py` (`DjangoStorage` class) bridges async aiogram with sync Django ORM using `@sync_to_async` decorators

### Key Components

- `bot/services/bot_handlers.py`: Main bot logic (`MacBot` class)
  - FSM states defined in `MacStates` class (get_request, chose_request_type, work_1 through work_finish)
  - All message handlers and conversation flow
  - Uses YAML config from `config/messages.yaml` for bot messages

- `bot/services/bot_storage.py`: Django ORM wrapper (`DjangoStorage`)
  - Async methods that use `@sync_to_async` to call Django ORM
  - Methods: `add_user()`, `get_user()`, `add_user_state()`, `get_statistics()`

- `bot/models.py`: Django data models
  - `TelegramProfile`: Links Django User to Telegram account, includes subscription fields
  - `StateType`: State definitions (state_name, description)
  - `UserState`: Junction table tracking which states users have visited

- `bot/management/commands/runbot.py`: Django management command to start the bot

### Configuration

- `.env` file: Contains sensitive settings (TELEGRAM_BOT_TOKEN, SECRET_KEY, etc.)
- `config/messages.yaml`: All bot messages and conversation text
- `chat_bot_mac/settings.py`: Django settings including:
  - Timezone: Europe/Moscow
  - Language: Russian (ru)
  - Telegram settings: TELEGRAM_BOT_TOKEN, MASTER_NAME
  - Redis settings for FSM storage (optional, falls back to MemoryStorage)

### Media Files

- Card images stored in `media/images/day/` and `media/images/night/`
- Images named as `00001.jpg` through `00010.jpg`
- Bot randomly selects one of 10 images based on user's card type choice

## Common Commands

### Development

```bash
# Install dependencies
pip install -r requirements.txt

# Database migrations
python manage.py makemigrations
python manage.py migrate

# Create superuser for Django admin
python manage.py createsuperuser

# Run bot
python manage.py runbot

# Django admin server (for viewing data)
python manage.py runserver
```

### Data Migration

Migrating from legacy `mac_bot` SQLite database:

```bash
# Dry run (preview without changes)
./migrate_data.sh

# Actual migration
./migrate_data.sh --migrate

# Or use Django command directly
python manage.py migrate_from_old_db --source ../chat_bot/sqlite.db --dry-run
python manage.py migrate_from_old_db --source ../chat_bot/sqlite.db
```

See `MIGRATION_GUIDE.md` for detailed migration documentation.

### Django Shell

```bash
python manage.py shell

# Example queries
from bot.models import TelegramProfile, StateType, UserState
TelegramProfile.objects.count()
StateType.objects.all()
UserState.objects.filter(state_type__state_name='work_finish').count()
```

## Bot Flow

1. User sends `/start`
2. Bot checks 24-hour cooldown (staff users bypass)
3. User enters their request (text)
4. User chooses request type (Психотерапевтический/Коучинговый)
5. User chooses card type (День/Ночь)
6. Bot sends random card image
7. Multi-step conversation (work_2 through work_7):
   - Feelings about the card
   - What they see
   - Pleasant/unpleasant characters
   - Characters' feelings
   - What's happening
8. Summary and reflection (work_result through work_result_5)
9. Offer to book consultation via inline button to master's Telegram
10. 24-hour reminder scheduled

## Important Implementation Details

### FSM Storage

The bot supports two FSM storage modes:

- **MemoryStorage** (default): In-memory, lost on restart
- **RedisStorage**: Persistent across restarts, enabled via `USE_REDIS=True` in .env

Storage selection happens in `MacBot._create_storage()`.

### Async/Sync Bridge

When adding new database operations:

1. Define method in `DjangoStorage` class
2. Use `@sync_to_async` decorator
3. Use standard Django ORM inside the method
4. Call as async from aiogram handlers

Example:
```python
@sync_to_async
def add_user_state(self, user_id: int, state_name: str, description: str = None):
    state_type, _ = StateType.objects.get_or_create(state_name=state_name)
    profile = TelegramProfile.objects.get(telegram_id=user_id)
    UserState.objects.create(telegram_profile=profile, state_type=state_type)
```

### Staff Commands

- `/send_all`: Broadcast message to all users (requires RedisStorage)
- `/stats`: Show bot statistics (total users, recent users, completed sessions)

Both require `User.is_staff = True` in Django admin.

### Logging

- Logger name: `mac_bot`
- Logs to: `bot_usage.log` and console
- All state changes are logged with user info

## Environment Variables

Required in `.env`:

```
SECRET_KEY=<django-secret-key>
DEBUG=True
TELEGRAM_BOT_TOKEN=<bot-token>
MASTER_NAME=<telegram-username>
USE_REDIS=False  # Set to True to enable Redis storage
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
```

## Testing Considerations

When testing bot changes:

- Use a test Telegram bot token to avoid affecting production
- Staff users (User.is_staff=True) can bypass 24-hour cooldown for rapid testing
- Mark test users as staff in Django admin for testing purposes
- Check `bot_usage.log` for detailed state transitions
- Use Django admin to inspect database state

## Database Schema Notes

- Each `TelegramProfile` requires a linked Django `User` (created with username `tg_{telegram_id}`)
- `UserState` records are created for every state transition (audit trail)
- Subscription fields exist but are not currently used in bot logic
- `last_request_time` tracking is handled in FSM state data, not in database model

## Health Checks

Two liveness probes, one per process:

- `GET /healthz` - the web app: Django answers and the database responds.
- `GET /healthz/bot` - the bot process: it runs in a separate container with no HTTP of
  its own, so it writes a heartbeat and this view reads it. 200, or 503 with a
  `problems` list.

`bot/services/heartbeat.py` holds both sides. The bot beats `loop` every 30s (proves the
event loop is not stuck) and calls `getMe` every 5 minutes (proves the Telegram session
is alive, not just the process). Stale after 180s and 900s respectively. The heartbeat
goes through the `bot_heartbeats` table, not Redis: Redis lives on the VPS host and only
the bot container can reach it (`network_mode: host`), while the database is mounted
into both.

This catches what `restart: always` cannot — a process that is up but stuck. Point an
external monitor (Uptime Kuma) at `https://mac.eremenko.live/healthz` and
`/healthz/bot`, accepted status `200`. Compose runs the same checks as container
healthchecks; the bot's uses `python manage.py healthcheck_bot`.

## Deployment

Project uses Docker Compose for deployment to VPS.

### Architecture
```
Internet → Nginx (80/443) → Django (8000)
                          ↓
                       Bot (polling) ← → Redis (host)
```

### Files
- `Dockerfile` - Python 3.13 image for Django + Bot
- `docker-compose.yml` - 3 services: nginx, django, bot
- `nginx.conf` - reverse proxy configuration
- `.github/workflows/deploy.yml` - auto-deploy on push to master
- `backup.sh` - automated backups (SQLite + Redis)

### Environment Variables
All configuration via environment variables (no .env files in repo):
- GitHub Secrets: SECRET_KEY, TELEGRAM_BOT_TOKEN, PRODAMUS_SECRET_KEY, VPS credentials
- GitHub Variables: ALLOWED_HOSTS, MASTER_NAME, Redis settings, PRODAMUS_MERCHANT_URL, PRODAMUS_TEST_MODE

### Bot Service
Uses `network_mode: host` to access existing Redis on VPS localhost.
Existing Redis data from old bot version is preserved.

### Common Commands
```bash
docker compose build
docker compose up -d
docker compose logs -f bot
docker compose restart django bot
```

### Deployment Process
1. Push to master branch
2. GitHub Actions triggers
3. SSH to VPS, pull code
4. Rebuild containers
5. Restart services
6. Verify with logs

See plan file for full deployment instructions.

## Prodamus Payment Integration

### Key Files
- `bot/services/prodamus_service.py`: `ProdamusService` class — signing, webhook verification, payment link creation
- `bot/views.py`: `prodamus_webhook`, `payment_select`, `payment_process` views
- `bot/templates/bot/payment_select.html`: tariff selection page
- `bot/templates/bot/payment_success.html`: post-payment success page

### Environment Variables
```
PRODAMUS_MERCHANT_URL=https://demo.payform.ru/   # prod: your shop URL from Prodamus dashboard
PRODAMUS_SECRET_KEY=<key from Prodamus dashboard>  # Settings → API → Secret key
PRODAMUS_TEST_MODE=True   # False in production
PRODAMUS_RETURN_URL=https://t.me/<bot_name>       # where user goes after payment
```

### Test Mode vs Production
- `PRODAMUS_TEST_MODE=True`: code appends `"demo"` suffix to secret key automatically (`key + "demo"`). No real charges. Use `PRODAMUS_MERCHANT_URL=https://demo.payform.ru/`.
- `PRODAMUS_TEST_MODE=False`: uses key as-is. Real charges. Use real merchant URL from dashboard.
- `PRODAMUS_SECRET_KEY` is always the real key from the dashboard — the suffix is added by code, not manually.

### Payment Flow
1. User clicks "Открыть полный доступ" in bot → `/payment/select/<token>/`
2. `payment_select` validates token, saves `telegram_id` to session, renders tariff page
3. User submits form → `payment_process` creates `Payment` record, calls Prodamus API for payment link
4. User redirected to Prodamus → pays → Prodamus calls `POST /api/prodamus/webhook`
5. Webhook verifies HMAC signature, updates `Payment.status`, calls `profile.activate_subscription()`

### Webhook Security
- Signature verified via HMAC SHA256 (`ProdamusPy.verify()`) before any processing
- **IMPORTANT**: Signature must be verified using `request.body` (raw POST data), not re-encoded dict
- Webhook endpoint is `@csrf_exempt` (Prodamus cannot send CSRF token)
- Only `payform.ru` and `prodamus.ru` domains are accepted for payment redirects (open redirect prevention)

### Subscription Model
- `Subscription`: tariff definition (`code`, `price`, `duration_days`, `daily_sessions_limit`, `cards_limit`)
- `Payment`: payment record linked to profile + subscription plan
- `TelegramProfile.activate_subscription(plan)`: sets `current_subscription`, calculates `subscription_expires_at`
- `TelegramProfile.is_subscribed`: property, returns True if subscription is active and not expired
- Free plan code: `"free"`. All other active plans shown on payment page.

### Button Text in payment_select.html
Button labels are derived from `plan.code`, not `plan.name` (which is the full Prodamus product name):
- `code == 'monthly'` → "Месяц — {price} ₽"
- `code == 'yearly'` → "Год — {price} ₽" + "−17%" badge
