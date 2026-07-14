"""Пульс бота: процесс бота его пишет, Django отдает наружу через /healthz/bot.

Бот и Django живут в разных контейнерах. Хостовый Redis виден только боту
(network_mode: host), поэтому единственный общий канал между ними - база, которая
и так смонтирована в оба контейнера.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone

from asgiref.sync import sync_to_async

logger = logging.getLogger("mac_bot")

LOOP = "loop"
TELEGRAM = "telegram"

LOOP_INTERVAL_SECONDS = 30
TELEGRAM_INTERVAL_SECONDS = 300

# Насколько пульс может опоздать, прежде чем подсистему считают залипшей
LOOP_STALE_SECONDS = 180
TELEGRAM_STALE_SECONDS = 900

TRACKED = ((LOOP, LOOP_STALE_SECONDS), (TELEGRAM, TELEGRAM_STALE_SECONDS))


def _write(name: str, beat_at: datetime) -> None:
    from bot.models import BotHeartbeat

    BotHeartbeat.objects.update_or_create(name=name, defaults={"beat_at": beat_at})


def read(name: str) -> datetime | None:
    """Время последнего пульса подсистемы (читает Django во вьюхе /healthz/bot)."""
    from bot.models import BotHeartbeat

    row = BotHeartbeat.objects.filter(name=name).first()
    return row.beat_at if row else None


async def beat(name: str) -> None:
    """Записать пульс подсистемы (вызывает процесс бота)."""
    await sync_to_async(_write)(name, datetime.now(timezone.utc))


def check() -> tuple[bool, dict]:
    """Жив ли процесс бота: свежий ли пульс event loop и связи с Telegram."""
    now = datetime.now(timezone.utc)
    problems = []
    last_tick = {}

    for name, limit in TRACKED:
        beat_at = read(name)
        if beat_at is None:
            problems.append(f"{name}: пульса нет, бот не отвечает")
            continue

        age = int((now - beat_at).total_seconds())
        last_tick[name] = age
        if age > limit:
            problems.append(f"{name}: последний пульс {age} с назад (лимит {limit} с)")

    details = {"status": "unhealthy" if problems else "ok", "last_tick": last_tick}
    if problems:
        details["problems"] = problems
    return not problems, details


async def run(bot) -> None:
    """Фоновая задача бота: пульс event loop раз в 30 с, getMe раз в 5 минут.

    getMe отделен от пульса loop: он отличает живой процесс от живой связи с Telegram
    (отозванный токен, сеть) и стоит запроса к API, поэтому идет реже.
    """
    last_telegram = 0.0

    while True:
        try:
            await beat(LOOP)

            if time.monotonic() - last_telegram >= TELEGRAM_INTERVAL_SECONDS:
                try:
                    await bot.get_me()
                except Exception as e:
                    logger.warning(f"Telegram не ответил на getMe: {e}")
                else:
                    await beat(TELEGRAM)
                    last_telegram = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Ошибка в задаче пульса: {e}")

        await asyncio.sleep(LOOP_INTERVAL_SECONDS)
