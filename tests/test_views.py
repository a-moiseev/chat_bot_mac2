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

    def _post_webhook(self, client, data, signature):
        """Отправить webhook с подписью в заголовке Sign"""
        return client.post("/api/prodamus/webhook", data, HTTP_SIGN=signature)

    def test_webhook_missing_fields(self):
        """Проверка валидации обязательных полей"""
        client = Client()
        # Нет order_num и нет заголовка Sign
        response = client.post("/api/prodamus/webhook", {"order_num": "ORDER_123"})
        assert response.status_code == 400
        assert "error" in response.json()

    def test_webhook_invalid_signature(self, telegram_profile, premium_subscription):
        """Проверка отклонения невалидной подписи"""
        Payment.objects.create(
            telegram_profile=telegram_profile,
            subscription_plan=premium_subscription,
            order_id="ORDER_123_monthly_abc",
            amount=300,
            status="pending",
        )

        client = Client()
        data = {
            "order_num": "ORDER_123_monthly_abc",
            "subscription[notification_code]": "activation",
        }
        response = self._post_webhook(client, data, "invalid_signature_12345")

        assert response.status_code == 403
        assert "Invalid signature" in response.json()["error"]

    def test_webhook_payment_not_found_returns_ok(self):
        """Activation с неизвестным order_num возвращает 200 (тестовые данные Prodamus)"""
        service = ProdamusService()
        data = {
            "order_num": "NONEXISTENT_ORDER",
            "subscription[notification_code]": "activation",
        }
        signature = service.generate_signature(data)

        client = Client()
        response = self._post_webhook(client, data, signature)

        # Возвращаем 200 чтобы Prodamus не повторял запрос
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_webhook_activation_by_user(self, telegram_profile, premium_subscription):
        """Активация подписки пользователем (первый платёж)"""
        payment = Payment.objects.create(
            telegram_profile=telegram_profile,
            subscription_plan=premium_subscription,
            order_id="ORDER_123_monthly_xyz",
            amount=300,
            status="pending",
        )

        service = ProdamusService()
        data = {
            "order_num": payment.order_id,
            "subscription[type]": "notification",
            "subscription[notification_code]": "activation",
            "subscription[initiator]": "user",
            "subscription[id]": "SUB_12345",
            "customer_extra": str(telegram_profile.telegram_id),
        }
        signature = service.generate_signature(data)

        response = self._post_webhook(Client(), data, signature)

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        payment.refresh_from_db()
        assert payment.status == "success"
        assert payment.subscription_id == "SUB_12345"
        assert payment.paid_at is not None

        telegram_profile.refresh_from_db()
        assert telegram_profile.current_subscription == premium_subscription
        assert telegram_profile.subscription_expires_at > timezone.now()

    def test_webhook_activation_by_manager(self, telegram_profile, premium_subscription):
        """Активация подписки менеджером (ручная активация в ЛК Prodamus)"""
        payment = Payment.objects.create(
            telegram_profile=telegram_profile,
            subscription_plan=premium_subscription,
            order_id="ORDER_MGR_monthly_xyz",
            amount=300,
            status="pending",
        )

        service = ProdamusService()
        data = {
            "order_num": payment.order_id,
            "subscription[type]": "notification",
            "subscription[notification_code]": "activation",
            "subscription[initiator]": "manager",
            "subscription[id]": "SUB_99999",
            "customer_extra": str(telegram_profile.telegram_id),
        }
        signature = service.generate_signature(data)

        response = self._post_webhook(Client(), data, signature)

        assert response.status_code == 200

        payment.refresh_from_db()
        assert payment.status == "success"

        telegram_profile.refresh_from_db()
        assert telegram_profile.current_subscription == premium_subscription
        assert telegram_profile.subscription_expires_at > timezone.now()

    def test_webhook_duplicate_activation(self, telegram_profile, premium_subscription):
        """Повторный activation не продлевает подписку второй раз"""
        payment = Payment.objects.create(
            telegram_profile=telegram_profile,
            subscription_plan=premium_subscription,
            order_id="ORDER_789_monthly_xyz",
            amount=300,
            status="success",
            paid_at=timezone.now(),
        )
        telegram_profile.activate_subscription(premium_subscription)
        original_expires = telegram_profile.subscription_expires_at

        service = ProdamusService()
        data = {
            "order_num": payment.order_id,
            "subscription[notification_code]": "activation",
        }
        signature = service.generate_signature(data)

        response = self._post_webhook(Client(), data, signature)

        assert response.status_code == 200
        telegram_profile.refresh_from_db()
        assert telegram_profile.subscription_expires_at == original_expires

    def test_webhook_renewal(self, subscribed_profile, premium_subscription):
        """Рекуррентное продление подписки (auto_payment)"""
        original_expires = subscribed_profile.subscription_expires_at

        service = ProdamusService()
        data = {
            "order_num": "ORDER_RENEWAL_001",
            "subscription[type]": "action",
            "subscription[action_code]": "auto_payment",
            "subscription[id]": "SUB_RENEWAL",
            "customer_extra": str(subscribed_profile.telegram_id),
        }
        signature = service.generate_signature(data)

        response = self._post_webhook(Client(), data, signature)

        assert response.status_code == 200

        subscribed_profile.refresh_from_db()
        expected = original_expires + timezone.timedelta(days=premium_subscription.duration_days)
        assert subscribed_profile.subscription_expires_at == expected

    def test_webhook_renewal_test_data(self):
        """Тестовый renewal от Prodamus с нераспознаваемым customer_extra — возвращает 200"""
        service = ProdamusService()
        data = {
            "order_num": "test",
            "subscription[type]": "action",
            "subscription[action_code]": "auto_payment",
            "subscription[id]": "9999999999",
            "customer_extra": "дополнительные данные",
        }
        signature = service.generate_signature(data)

        response = self._post_webhook(Client(), data, signature)

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_webhook_deactivation(self, subscribed_profile):
        """Деактивация подписки"""
        assert subscribed_profile.is_subscribed is True

        service = ProdamusService()
        data = {
            "order_num": "ORDER_DEACT_001",
            "subscription[type]": "notification",
            "subscription[notification_code]": "deactivation",
            "subscription[id]": "SUB_DEACT",
            "customer_extra": str(subscribed_profile.telegram_id),
        }
        signature = service.generate_signature(data)

        response = self._post_webhook(Client(), data, signature)

        assert response.status_code == 200

        subscribed_profile.refresh_from_db()
        assert subscribed_profile.is_subscribed is False

    def test_webhook_reminder(self):
        """Уведомление о предстоящем списании — только 200, никаких изменений"""
        service = ProdamusService()
        data = {
            "order_num": "test",
            "subscription[type]": "notification",
            "subscription[notification_code]": "auto_payment_reminder",
            "customer_extra": "дополнительные данные",
        }
        signature = service.generate_signature(data)

        response = self._post_webhook(Client(), data, signature)

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_webhook_without_subscription_plan(self, telegram_profile):
        """Активация платежа без привязанного тарифа — webhook принят, подписка не изменена"""
        payment = Payment.objects.create(
            telegram_profile=telegram_profile,
            subscription_plan=None,
            order_id="ORDER_999_test",
            amount=300,
            status="pending",
        )

        service = ProdamusService()
        data = {
            "order_num": payment.order_id,
            "subscription[notification_code]": "activation",
        }
        signature = service.generate_signature(data)

        response = self._post_webhook(Client(), data, signature)

        assert response.status_code == 200

        payment.refresh_from_db()
        assert payment.status == "success"

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
        # Проверяем что оба тарифа отображаются (по code в value кнопки)
        assert 'value="monthly"' in content
        assert 'value="yearly"' in content

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
class TestSubscriptionInfo:
    """Тесты страницы информации о подписке"""

    def test_valid_token_free_user_renders(self, telegram_profile):
        """Страница открывается для free-пользователя"""
        token = generate_payment_token(
            telegram_profile.telegram_id, telegram_profile.username
        )

        client = Client()
        response = client.get(f"/subscription/info/{token}/")

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Ваша подписка" in content

    def test_valid_token_premium_user_shows_expiry(self, subscribed_profile):
        """Дата окончания подписки отображается для premium-пользователя"""
        token = generate_payment_token(
            subscribed_profile.telegram_id, subscribed_profile.username
        )

        client = Client()
        response = client.get(f"/subscription/info/{token}/")

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        expires_str = timezone.localtime(subscribed_profile.subscription_expires_at).strftime("%d.%m.%Y")
        assert expires_str in content

    def test_free_user_sees_upgrade_button(self, telegram_profile):
        """Free-пользователь видит кнопку 'Выбрать тариф' со ссылкой на payment_select"""
        token = generate_payment_token(
            telegram_profile.telegram_id, telegram_profile.username
        )

        client = Client()
        response = client.get(f"/subscription/info/{token}/")

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Выбрать тариф" in content
        assert f"/payment/select/{token}/" in content

    def test_invalid_token_shows_error(self):
        """Невалидный токен показывает ошибку"""
        client = Client()
        response = client.get("/subscription/info/invalid_token_xyz/")

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "недействительна" in content

    def test_user_not_found_shows_error(self):
        """Несуществующий пользователь показывает ошибку"""
        token = generate_payment_token(999999999, "ghost")

        client = Client()
        response = client.get(f"/subscription/info/{token}/")

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "недействительна" in content

    def test_post_not_allowed(self, telegram_profile):
        """POST метод не разрешен"""
        token = generate_payment_token(
            telegram_profile.telegram_id, telegram_profile.username
        )

        client = Client()
        response = client.post(f"/subscription/info/{token}/")

        assert response.status_code == 405


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
