"""Утилита для генерации и валидации токенов оплаты

Используется для создания защищенных ссылок на страницу выбора тарифа.
Токены подписаны HMAC SHA256 с использованием Django SECRET_KEY.
"""

import logging
from typing import Optional

from django.core import signing

logger = logging.getLogger("mac_bot")

# Срок действия токена в секундах (24 часа)
PAYMENT_TOKEN_MAX_AGE = 24 * 60 * 60


def generate_payment_token(telegram_id: int, username: Optional[str] = None) -> str:
    """Генерация подписанного токена для страницы оплаты

    Args:
        telegram_id: Telegram ID пользователя
        username: Telegram username (опционально)

    Returns:
        Подписанный токен (URL-safe base64)
    """
    data = {
        "telegram_id": telegram_id,
        "username": username or "",
    }

    token = signing.dumps(data, salt="payment_token")

    logger.info(f"[PAYMENT_TOKEN] Generated token for user {telegram_id} (@{username})")

    return token


def validate_payment_token(token: str) -> Optional[dict]:
    """Проверка и декодирование токена оплаты

    Args:
        token: Подписанный токен

    Returns:
        Словарь с данными {telegram_id, username} или None если токен невалиден
    """
    try:
        data = signing.loads(token, salt="payment_token", max_age=PAYMENT_TOKEN_MAX_AGE)

        logger.info(f"[PAYMENT_TOKEN] Valid token for user {data.get('telegram_id')}")

        return data

    except signing.SignatureExpired:
        logger.warning("[PAYMENT_TOKEN] Token expired")
        return None

    except signing.BadSignature:
        logger.warning("[PAYMENT_TOKEN] Invalid token signature")
        return None

    except Exception as e:
        logger.error(f"[PAYMENT_TOKEN] Unexpected error validating token: {e}")
        return None
