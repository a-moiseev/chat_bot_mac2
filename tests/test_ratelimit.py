"""Лимитер должен считать по клиенту, а не по прокси.

За nginx REMOTE_ADDR одинаковый для всех, поэтому key="ip" складывал всех
посетителей в один счетчик: 11 попыток оплаты в минуту суммарно - и 403 всем.
"""

import pytest
from django.core.cache import cache
from django.test import RequestFactory

from bot.views import client_ip

PAYMENT_PROCESS_LIMIT = 10


@pytest.fixture
def clean_limits(db):
    """Счетчики лимитера живут в БД, между тестами их надо сбрасывать"""
    cache.clear()
    yield
    cache.clear()


def _post_payment(client, ip, token="bogus-token"):
    return client.post(f"/payment/process/{token}/", HTTP_X_REAL_IP=ip)


def test_client_ip_prefers_real_ip_header():
    request = RequestFactory().get("/", HTTP_X_REAL_IP="203.0.113.7", REMOTE_ADDR="172.18.0.5")

    assert client_ip("group", request) == "203.0.113.7"


def test_client_ip_falls_back_to_remote_addr():
    # запуск без nginx: заголовка нет, считаем по адресу соединения
    request = RequestFactory().get("/", REMOTE_ADDR="172.18.0.5")

    assert client_ip("group", request) == "172.18.0.5"


def test_one_client_does_not_block_another(client, clean_limits):
    """Главный регресс: выжатый лимит одного IP не должен ронять остальных"""
    for _ in range(PAYMENT_PROCESS_LIMIT + 1):
        _post_payment(client, "203.0.113.7")

    assert _post_payment(client, "203.0.113.7").status_code == 403
    assert _post_payment(client, "198.51.100.3").status_code != 403


def test_limit_still_blocks_single_client(client, clean_limits):
    """Лимит не должен просто отключиться: один клиент по-прежнему упирается"""
    responses = [
        _post_payment(client, "203.0.113.7").status_code
        for _ in range(PAYMENT_PROCESS_LIMIT + 5)
    ]

    assert 403 in responses


def test_counter_is_shared_between_workers(settings):
    """Счетчик должен жить в общем кэше, а не в памяти процесса"""
    assert "LocMemCache" not in settings.CACHES["default"]["BACKEND"]
