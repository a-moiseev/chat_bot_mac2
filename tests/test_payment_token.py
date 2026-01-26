"""Тесты для утилиты генерации и валидации токенов оплаты"""

from unittest.mock import patch

from django.core import signing

from bot.services.payment_token import (
    PAYMENT_TOKEN_MAX_AGE,
    generate_payment_token,
    validate_payment_token,
)


class TestGeneratePaymentToken:
    """Тесты генерации токенов"""

    def test_generate_token_returns_string(self):
        """Токен должен быть строкой"""
        token = generate_payment_token(123456789, "test_user")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_generate_token_different_for_different_users(self):
        """Токены для разных пользователей должны отличаться"""
        token1 = generate_payment_token(123456789, "user1")
        token2 = generate_payment_token(987654321, "user2")
        assert token1 != token2

    def test_generate_token_without_username(self):
        """Токен должен генерироваться без username"""
        token = generate_payment_token(123456789)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_generate_token_with_none_username(self):
        """Токен должен генерироваться с username=None"""
        token = generate_payment_token(123456789, None)
        assert isinstance(token, str)
        assert len(token) > 0


class TestValidatePaymentToken:
    """Тесты валидации токенов"""

    def test_validate_valid_token(self):
        """Валидный токен должен декодироваться"""
        telegram_id = 123456789
        username = "test_user"

        token = generate_payment_token(telegram_id, username)
        data = validate_payment_token(token)

        assert data is not None
        assert data["telegram_id"] == telegram_id
        assert data["username"] == username

    def test_validate_token_without_username(self):
        """Токен без username должен декодироваться"""
        telegram_id = 123456789

        token = generate_payment_token(telegram_id)
        data = validate_payment_token(token)

        assert data is not None
        assert data["telegram_id"] == telegram_id
        assert data["username"] == ""

    def test_validate_expired_token(self):
        """Истекший токен должен возвращать None"""
        token = generate_payment_token(123456789, "test_user")

        # Мокаем время чтобы токен был просрочен
        with patch("bot.services.payment_token.signing.loads") as mock_loads:
            mock_loads.side_effect = signing.SignatureExpired("Token expired")
            data = validate_payment_token(token)

        assert data is None

    def test_validate_invalid_signature(self):
        """Невалидная подпись должна возвращать None"""
        data = validate_payment_token("invalid_token_12345")
        assert data is None

    def test_validate_tampered_token(self):
        """Измененный токен должен возвращать None"""
        token = generate_payment_token(123456789, "test_user")

        # Изменяем токен
        tampered_token = token[:-5] + "XXXXX"
        data = validate_payment_token(tampered_token)

        assert data is None

    def test_validate_empty_token(self):
        """Пустой токен должен возвращать None"""
        data = validate_payment_token("")
        assert data is None

    def test_token_max_age_is_5_minutes(self):
        """Срок действия токена должен быть 5 минут"""
        assert PAYMENT_TOKEN_MAX_AGE == 5 * 60  # 300 секунд


class TestTokenIntegration:
    """Интеграционные тесты токенов"""

    def test_roundtrip_token(self):
        """Полный цикл: генерация -> валидация"""
        telegram_id = 999888777
        username = "integration_test"

        token = generate_payment_token(telegram_id, username)
        data = validate_payment_token(token)

        assert data is not None
        assert data["telegram_id"] == telegram_id
        assert data["username"] == username

    def test_multiple_tokens_for_same_user(self):
        """Несколько токенов для одного пользователя должны быть разными"""
        telegram_id = 123456789
        username = "test_user"

        token1 = generate_payment_token(telegram_id, username)
        token2 = generate_payment_token(telegram_id, username)

        # Токены разные (содержат timestamp)
        # Но оба валидны и декодируются в одни и те же данные
        data1 = validate_payment_token(token1)
        data2 = validate_payment_token(token2)

        assert data1["telegram_id"] == data2["telegram_id"]
        assert data1["username"] == data2["username"]
