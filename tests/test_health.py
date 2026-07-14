from datetime import timedelta

import pytest
from django.utils import timezone

from bot.models import BotHeartbeat
from bot.services import heartbeat


@pytest.fixture
def alive_bot(db):
    """Бот только что отчитался обоими пульсами"""
    now = timezone.now()
    BotHeartbeat.objects.create(name=heartbeat.LOOP, beat_at=now)
    BotHeartbeat.objects.create(name=heartbeat.TELEGRAM, beat_at=now)


def test_healthz_ok(client, db):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_healthz_bot_ok(client, alive_bot):
    response = client.get("/healthz/bot")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_healthz_bot_without_heartbeat(client, db):
    response = client.get("/healthz/bot")

    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"


def test_healthz_bot_stale_loop(client, alive_bot):
    stale = timezone.now() - timedelta(seconds=heartbeat.LOOP_STALE_SECONDS + 1)
    BotHeartbeat.objects.filter(name=heartbeat.LOOP).update(beat_at=stale)

    response = client.get("/healthz/bot")

    assert response.status_code == 503
    assert any("loop" in problem for problem in response.json()["problems"])


def test_healthz_bot_stale_telegram_only(client, alive_bot):
    # процесс бота жив, но связь с Telegram потеряна
    stale = timezone.now() - timedelta(seconds=heartbeat.TELEGRAM_STALE_SECONDS + 1)
    BotHeartbeat.objects.filter(name=heartbeat.TELEGRAM).update(beat_at=stale)

    response = client.get("/healthz/bot")

    assert response.status_code == 503
    assert all("telegram" in problem for problem in response.json()["problems"])


def test_beat_keeps_one_row_per_subsystem(db):
    heartbeat._write(heartbeat.LOOP, timezone.now())
    heartbeat._write(heartbeat.LOOP, timezone.now())

    assert BotHeartbeat.objects.filter(name=heartbeat.LOOP).count() == 1
