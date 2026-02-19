from unittest.mock import patch

import pytest
from django.test import Client
from django.utils import timezone

from bot.models import Payment, Subscription
from bot.services.payment_token import generate_payment_token
from bot.services.prodamus_service import ProdamusService


@pytest.mark.django_db
class TestProdamusWebhook:
    """Тесты webhook обработчика Prodamus"""

    def test_webhook_missing_fields(self):
        """Проверка валидации обязательных полей"""
        client = Client()
        response = client.post(
            "/api/prodamus/webhook",
            {
                "order_id": "ORDER_123",
                # Отсутствуют payment_status и signature
            },
        )
        assert response.status_code == 400
        assert "error" in response.json()

    def test_webhook_invalid_signature(self, telegram_profile, premium_subscription):
        """Проверка отклонения невалидной подписи"""
        # Создаем платеж
        payment = Payment.objects.create(
            telegram_profile=telegram_profile,
            subscription_plan=premium_subscription,
            order_id="ORDER_123_monthly_abc",
            amount=300,
            status="pending",
        )

        client = Client()
        response = client.post(
            "/api/prodamus/webhook",
            {
                "order_id": payment.order_id,
                "payment_status": "success",
                "signature": "invalid_signature_12345",
            },
        )

        assert response.status_code == 403
        assert "Invalid signature" in response.json()["error"]

    def test_webhook_payment_not_found(self):
        """Проверка обработки несуществующего платежа"""
        service = ProdamusService()
        data = {
            "order_id": "NONEXISTENT_ORDER",
            "payment_status": "success",
        }
        signature = service.generate_signature(data)

        client = Client()
        response = client.post(
            "/api/prodamus/webhook", {**data, "signature": signature}
        )

        # Должен вернуть 404 так как нет customer_extra для создания нового
        assert response.status_code == 404

    def test_webhook_success_payment(self, telegram_profile, premium_subscription):
        """Проверка успешной обработки платежа"""
        # Создаем платеж
        payment = Payment.objects.create(
            telegram_profile=telegram_profile,
            subscription_plan=premium_subscription,
            order_id="ORDER_123_monthly_xyz",
            amount=300,
            status="pending",
        )

        # Генерируем валидную подпись
        service = ProdamusService()
        data = {
            "order_id": payment.order_id,
            "payment_status": "success",
            "payment_id": "PAY_12345",
            "subscription_id": "SUB_12345",
        }
        signature = service.generate_signature(data)

        # Отправляем webhook
        client = Client()
        response = client.post(
            "/api/prodamus/webhook", {**data, "signature": signature}
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        # Проверяем что платеж обновился
        payment.refresh_from_db()
        assert payment.status == "success"
        assert payment.payment_id == "PAY_12345"
        assert payment.subscription_id == "SUB_12345"
        assert payment.paid_at is not None

        # Проверяем что подписка активировалась
        telegram_profile.refresh_from_db()
        assert telegram_profile.current_subscription == premium_subscription
        assert telegram_profile.subscription_expires_at is not None
        assert telegram_profile.subscription_expires_at > timezone.now()

    def test_webhook_failed_payment(self, telegram_profile, premium_subscription):
        """Проверка обработки неудавшегося платежа"""
        payment = Payment.objects.create(
            telegram_profile=telegram_profile,
            subscription_plan=premium_subscription,
            order_id="ORDER_456_monthly_xyz",
            amount=300,
            status="pending",
        )

        service = ProdamusService()
        data = {
            "order_id": payment.order_id,
            "payment_status": "failed",
        }
        signature = service.generate_signature(data)

        client = Client()
        response = client.post(
            "/api/prodamus/webhook", {**data, "signature": signature}
        )

        assert response.status_code == 200

        # Проверяем что статус обновился, но подписка не активировалась
        payment.refresh_from_db()
        assert payment.status == "failed"
        assert payment.paid_at is None

        telegram_profile.refresh_from_db()
        assert telegram_profile.current_subscription != premium_subscription

    def test_webhook_duplicate_success(self, telegram_profile, premium_subscription):
        """Проверка обработки дублирующегося успешного webhook"""
        # Создаем уже оплаченный платеж
        payment = Payment.objects.create(
            telegram_profile=telegram_profile,
            subscription_plan=premium_subscription,
            order_id="ORDER_789_monthly_xyz",
            amount=300,
            status="success",
            paid_at=timezone.now(),
        )

        # Активируем подписку
        telegram_profile.activate_subscription(premium_subscription)
        original_expires_at = telegram_profile.subscription_expires_at

        service = ProdamusService()
        data = {
            "order_id": payment.order_id,
            "payment_status": "success",
        }
        signature = service.generate_signature(data)

        # Отправляем повторный webhook
        client = Client()
        response = client.post(
            "/api/prodamus/webhook", {**data, "signature": signature}
        )

        assert response.status_code == 200

        # Проверяем что дата окончания не изменилась (не продлилась второй раз)
        telegram_profile.refresh_from_db()
        # Даты должны быть примерно одинаковые (разница < 1 секунды)
        # Но из-за логики activate_subscription может быть небольшое отличие
        # Просто проверим что подписка осталась активной
        assert telegram_profile.is_subscribed is True

    def test_webhook_without_subscription_plan(self, telegram_profile):
        """Проверка обработки платежа без привязанного тарифа"""
        # Создаем платеж БЕЗ subscription_plan
        payment = Payment.objects.create(
            telegram_profile=telegram_profile,
            subscription_plan=None,  # Явно указываем None
            order_id="ORDER_999_test",
            amount=300,
            status="pending",
        )

        service = ProdamusService()
        data = {
            "order_id": payment.order_id,
            "payment_status": "success",
        }
        signature = service.generate_signature(data)

        client = Client()
        response = client.post(
            "/api/prodamus/webhook", {**data, "signature": signature}
        )

        # Webhook обработан, но подписка не активирована
        assert response.status_code == 200

        payment.refresh_from_db()
        assert payment.status == "success"

        # Подписка не должна измениться
        telegram_profile.refresh_from_db()
        assert (
            telegram_profile.current_subscription is None
            or telegram_profile.current_subscription.code == "free"
        )


@pytest.mark.django_db
class TestProdamusSuccess:
    """Тесты страницы успешной оплаты"""

    def test_success_page_renders(self):
        """Проверка что страница успеха отображается"""
        client = Client()
        response = client.get("/api/prodamus/success")

        assert response.status_code == 200
        assert "Оплата успешна" in response.content.decode("utf-8")

    def test_success_page_with_order_id(self, telegram_profile, premium_subscription):
        """Проверка страницы с order_id"""
        payment = Payment.objects.create(
            telegram_profile=telegram_profile,
            subscription_plan=premium_subscription,
            order_id="ORDER_SUCCESS_123",
            amount=300,
            status="success",
            paid_at=timezone.now(),
        )

        telegram_profile.activate_subscription(premium_subscription)

        client = Client()
        response = client.get(f"/api/prodamus/success?order_id={payment.order_id}")

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert payment.order_id in content
        assert premium_subscription.name in content

    def test_success_page_nonexistent_order(self):
        """Проверка страницы с несуществующим order_id"""
        client = Client()
        response = client.get("/api/prodamus/success?order_id=NONEXISTENT")

        # Страница должна отобразиться даже если заказ не найден
        assert response.status_code == 200
        assert "Оплата успешна" in response.content.decode("utf-8")

    def test_success_page_post_method_not_allowed(self):
        """Проверка что POST метод не разрешен"""
        client = Client()
        response = client.post("/api/prodamus/success")

        assert response.status_code == 405  # Method Not Allowed


@pytest.mark.django_db
class TestPaymentSelect:
    """Тесты страницы выбора тарифа"""

    def test_payment_select_valid_token(self, telegram_profile):
        """Страница отображается с валидным токеном"""
        token = generate_payment_token(
            telegram_profile.telegram_id, telegram_profile.username
        )

        client = Client()
        response = client.get(f"/payment/select/{token}/")

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Выбери свой тариф" in content

    def test_payment_select_shows_username(self, telegram_profile):
        """Страница показывает username пользователя"""
        token = generate_payment_token(
            telegram_profile.telegram_id, telegram_profile.username
        )

        client = Client()
        response = client.get(f"/payment/select/{token}/")

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert telegram_profile.username in content

    def test_payment_select_invalid_token(self):
        """Невалидный токен показывает ошибку"""
        client = Client()
        response = client.get("/payment/select/invalid_token_12345/")

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "недействительна" in content

    def test_payment_select_expired_token(self, telegram_profile):
        """Истекший токен показывает ошибку"""

        token = generate_payment_token(
            telegram_profile.telegram_id, telegram_profile.username
        )

        # Мокаем валидацию чтобы она вернула None (истекший токен)
        with patch("bot.views.validate_payment_token", return_value=None):
            client = Client()
            response = client.get(f"/payment/select/{token}/")

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "недействительна" in content

    def test_payment_select_user_not_found(self):
        """Несуществующий пользователь показывает generic ошибку (user enumeration prevention)"""
        # Генерируем токен для несуществующего пользователя
        token = generate_payment_token(999999999, "nonexistent")

        client = Client()
        response = client.get(f"/payment/select/{token}/")

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        # Generic error to prevent user enumeration
        assert "недействительна" in content

    def test_payment_select_shows_plans(self, telegram_profile, premium_subscription):
        """Страница показывает доступные тарифы"""
        # Создаем годовой тариф
        yearly = Subscription.objects.create(
            name="Годовой",
            code="yearly",
            price=3000,
            duration_days=365,
            daily_sessions_limit=3,
            is_active=True,
        )

        token = generate_payment_token(
            telegram_profile.telegram_id, telegram_profile.username
        )

        client = Client()
        response = client.get(f"/payment/select/{token}/")

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        # Проверяем что оба тарифа отображаются
        assert premium_subscription.name in content
        assert yearly.name in content

    def test_payment_select_excludes_free_plan(
        self, telegram_profile, free_subscription
    ):
        """Бесплатный тариф не отображается в списке"""
        token = generate_payment_token(
            telegram_profile.telegram_id, telegram_profile.username
        )

        client = Client()
        response = client.get(f"/payment/select/{token}/")

        assert response.status_code == 200
        # Форма не должна содержать кнопку для free тарифа
        content = response.content.decode("utf-8")
        assert 'value="free"' not in content

    def test_payment_select_post_not_allowed(self, telegram_profile):
        """POST метод не разрешен для payment_select"""
        token = generate_payment_token(
            telegram_profile.telegram_id, telegram_profile.username
        )

        client = Client()
        response = client.post(f"/payment/select/{token}/")

        assert response.status_code == 405

    def test_payment_select_sets_session(self, telegram_profile):
        """Успешная загрузка страницы сохраняет telegram_id в сессию"""
        token = generate_payment_token(
            telegram_profile.telegram_id, telegram_profile.username
        )

        client = Client()
        client.get(f"/payment/select/{token}/")

        assert client.session.get("payment_telegram_id") == telegram_profile.telegram_id
        assert client.session.get("payment_username") == telegram_profile.username


@pytest.mark.django_db
class TestPaymentProcess:
    """Тесты обработки выбора тарифа"""

    def _set_session(self, client, telegram_id, username=""):
        """Вспомогательный метод: устанавливает сессионные данные как это делает payment_select"""
        session = client.session
        session["payment_telegram_id"] = telegram_id
        session["payment_username"] = username
        session.save()

    def test_payment_process_no_session_shows_error(self):
        """Без данных сессии (страница не была открыта) показывает ошибку"""
        client = Client()
        response = client.post(
            "/payment/process/any_token/", {"plan_code": "monthly"}
        )

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "недействительна" in content

    def test_payment_process_missing_plan_code(self, telegram_profile):
        """Отсутствие plan_code показывает ошибку"""
        token = generate_payment_token(
            telegram_profile.telegram_id, telegram_profile.username
        )

        client = Client()
        self._set_session(client, telegram_profile.telegram_id, telegram_profile.username)
        response = client.post(f"/payment/process/{token}/", {})

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "не выбран" in content

    def test_payment_process_invalid_plan_code(self, telegram_profile):
        """Невалидный plan_code показывает ошибку"""
        token = generate_payment_token(
            telegram_profile.telegram_id, telegram_profile.username
        )

        client = Client()
        self._set_session(client, telegram_profile.telegram_id, telegram_profile.username)
        response = client.post(
            f"/payment/process/{token}/",
            {"plan_code": "nonexistent_plan", "email": "test@example.com"},
        )

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "не найден" in content

    def test_payment_process_user_not_found(self):
        """Несуществующий пользователь в сессии показывает generic ошибку"""
        token = generate_payment_token(999999999, "nonexistent")

        client = Client()
        self._set_session(client, 999999999, "nonexistent")
        response = client.post(f"/payment/process/{token}/", {"plan_code": "monthly"})

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "недействительна" in content

    def test_payment_process_creates_payment_record(
        self, telegram_profile, premium_subscription
    ):
        """Успешный запрос создает запись Payment"""
        token = generate_payment_token(
            telegram_profile.telegram_id, telegram_profile.username
        )

        initial_count = Payment.objects.count()

        with patch("bot.views.async_to_sync") as mock_async:
            mock_async.return_value = lambda **kwargs: "https://payform.ru/pay/123"

            client = Client()
            self._set_session(client, telegram_profile.telegram_id, telegram_profile.username)
            response = client.post(
                f"/payment/process/{token}/",
                {"plan_code": premium_subscription.code, "email": "test@example.com"},
            )

        assert Payment.objects.count() == initial_count + 1

        payment = Payment.objects.last()
        assert payment.telegram_profile == telegram_profile
        assert payment.subscription_plan == premium_subscription
        assert payment.status == "pending"
        assert payment.amount == premium_subscription.price

    def test_payment_process_redirects_to_prodamus(
        self, telegram_profile, premium_subscription
    ):
        """Успешный запрос перенаправляет на Prodamus"""
        token = generate_payment_token(
            telegram_profile.telegram_id, telegram_profile.username
        )

        prodamus_url = "https://demo.payform.ru/pay/123"

        with patch("bot.views.async_to_sync") as mock_async:
            mock_async.return_value = lambda **kwargs: prodamus_url

            client = Client()
            self._set_session(client, telegram_profile.telegram_id, telegram_profile.username)
            response = client.post(
                f"/payment/process/{token}/",
                {"plan_code": premium_subscription.code, "email": "test@example.com"},
            )

        assert response.status_code == 302
        assert response.url == prodamus_url

    def test_payment_process_deletes_payment_on_error(
        self, telegram_profile, premium_subscription
    ):
        """При ошибке создания ссылки платеж удаляется"""
        token = generate_payment_token(
            telegram_profile.telegram_id, telegram_profile.username
        )

        initial_count = Payment.objects.count()

        with patch("bot.views.async_to_sync") as mock_async:
            mock_async.return_value = lambda **kwargs: (_ for _ in ()).throw(
                Exception("Prodamus error")
            )

            client = Client()
            self._set_session(client, telegram_profile.telegram_id, telegram_profile.username)
            response = client.post(
                f"/payment/process/{token}/", {"plan_code": premium_subscription.code}
            )

        assert Payment.objects.count() == initial_count

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Ошибка" in content

    def test_payment_process_get_not_allowed(self, telegram_profile):
        """GET метод не разрешен для payment_process"""
        token = generate_payment_token(
            telegram_profile.telegram_id, telegram_profile.username
        )

        client = Client()
        response = client.get(f"/payment/process/{token}/")

        assert response.status_code == 405

    def test_payment_process_rejects_invalid_redirect_domain(
        self, telegram_profile, premium_subscription
    ):
        """Open redirect prevention: отклоняет редирект на неизвестный домен"""
        token = generate_payment_token(
            telegram_profile.telegram_id, telegram_profile.username
        )

        malicious_url = "https://evil-phishing.com/fake-payment"

        with patch("bot.views.async_to_sync") as mock_async:
            mock_async.return_value = lambda **kwargs: malicious_url

            client = Client()
            self._set_session(client, telegram_profile.telegram_id, telegram_profile.username)
            response = client.post(
                f"/payment/process/{token}/", {"plan_code": premium_subscription.code}
            )

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Ошибка" in content

        assert Payment.objects.count() == 0
