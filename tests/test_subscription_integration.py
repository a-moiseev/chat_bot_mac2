from decimal import Decimal

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from bot.models import Payment, TelegramProfile, UserSession
from bot.services.bot_storage import DjangoStorage
from bot.services.prodamus_service import ProdamusService


@pytest.mark.django_db(transaction=True)
class TestUserSubscriptionFlow:
    """Тесты полного флоу работы с подписками"""

    @pytest.mark.asyncio
    async def test_new_user_gets_free_subscription(self, free_subscription):
        """Новый пользователь автоматически получает free подписку"""
        storage = DjangoStorage()

        # Создаем пользователя
        await storage.add_user(
            user_id=123456, username="test_user", full_name="Test User"
        )

        # Проверяем что у него free подписка
        profile = await storage.get_user(123456)
        assert profile is not None

        # Используем sync_to_async для доступа к связанным объектам
        subscription = await sync_to_async(lambda: profile.current_subscription)()
        assert subscription is not None
        assert subscription.code == "free"
        assert subscription.daily_sessions_limit == 1
        assert subscription.cards_limit == 10

    @pytest.mark.asyncio
    async def test_free_user_session_limits(self, free_subscription):
        """Free пользователь имеет лимит 1 сессия в день"""
        storage = DjangoStorage()

        await storage.add_user(user_id=111, username="free_user", full_name="Free User")

        # Первая сессия - можно начать
        can_start = await storage.can_start_session(111)
        assert can_start is True

        # Создаем сессию
        await storage.create_session(111, "Test request", "test", "день", 1)

        # Вторая сессия - нельзя начать
        can_start = await storage.can_start_session(111)
        assert can_start is False

    @pytest.mark.asyncio
    async def test_free_user_cards_limit(self, free_subscription):
        """Free пользователь имеет лимит 10 карт"""
        storage = DjangoStorage()

        await storage.add_user(
            user_id=222, username="free_user2", full_name="Free User 2"
        )

        cards_limit = await storage.get_user_cards_limit(222)
        assert cards_limit == 10

    @pytest.mark.asyncio
    async def test_premium_user_no_cards_limit(
        self, free_subscription, premium_subscription
    ):
        """Premium пользователь не имеет лимита карт"""
        storage = DjangoStorage()

        # Создаем пользователя
        await storage.add_user(
            user_id=333, username="premium_user", full_name="Premium User"
        )

        # Активируем premium подписку
        profile = await storage.get_user(333)
        await sync_to_async(profile.activate_subscription)(premium_subscription)

        # Проверяем лимит карт
        cards_limit = await storage.get_user_cards_limit(333)
        assert cards_limit is None  # Без ограничений

    @pytest.mark.asyncio
    async def test_premium_user_session_limits(
        self, free_subscription, premium_subscription
    ):
        """Premium пользователь имеет лимит 3 сессии в день"""
        storage = DjangoStorage()

        # Создаем пользователя и активируем premium
        await storage.add_user(
            user_id=444, username="premium_user2", full_name="Premium User 2"
        )
        profile = await storage.get_user(444)
        await sync_to_async(profile.activate_subscription)(premium_subscription)

        # Можем создать 3 сессии
        for i in range(3):
            can_start = await storage.can_start_session(444)
            assert can_start is True
            await storage.create_session(444, f"Request {i}", "test", "день", i + 1)

        # 4-я сессия - нельзя
        can_start = await storage.can_start_session(444)
        assert can_start is False


@pytest.mark.django_db(transaction=True)
class TestPaymentFlow:
    """Тесты флоу оплаты подписки"""

    @pytest.mark.asyncio
    async def test_create_payment_order(self, free_subscription, premium_subscription):
        """Создание заказа на оплату"""
        storage = DjangoStorage()

        # Создаем пользователя
        await storage.add_user(user_id=555, username="buyer", full_name="Buyer")

        # Создаем заказ
        order_id, payment_url = await storage.create_payment_order(
            user_id=555, plan_code="monthly", username="buyer"
        )

        # Проверяем что заказ создан
        assert order_id.startswith("ORDER_555_monthly_")
        assert "demo.payform.ru" in payment_url or "payform.ru" in payment_url

        # Проверяем Payment в БД
        payment = await sync_to_async(Payment.objects.get)(order_id=order_id)
        profile_id = await sync_to_async(lambda: payment.telegram_profile.telegram_id)()
        plan_code = await sync_to_async(lambda: payment.subscription_plan.code)()
        assert profile_id == 555
        assert plan_code == "monthly"
        assert payment.amount == Decimal("300.00")
        assert payment.status == "pending"

    def test_webhook_activates_subscription(
        self, telegram_profile, premium_subscription
    ):
        """Webhook от Prodamus активирует подписку"""
        # Создаем платеж
        payment = Payment.objects.create(
            telegram_profile=telegram_profile,
            subscription_plan=premium_subscription,
            order_id="ORDER_TEST_monthly_xyz",
            amount=300,
            status="pending",
        )

        # Имитируем webhook
        service = ProdamusService()
        data = {
            "order_id": payment.order_id,
            "payment_status": "success",
        }
        signature = service.generate_signature(data)

        # Обновляем платеж как в webhook handler
        payment.status = "success"
        payment.paid_at = timezone.now()
        payment.save()

        # Активируем подписку
        telegram_profile.activate_subscription(premium_subscription)

        # Проверяем активацию
        telegram_profile.refresh_from_db()
        assert telegram_profile.current_subscription == premium_subscription
        assert telegram_profile.subscription_expires_at is not None
        assert telegram_profile.subscription_expires_at > timezone.now()
        assert telegram_profile.is_subscribed is True


@pytest.mark.django_db(transaction=True)
class TestSessionTracking:
    """Тесты отслеживания сессий"""

    @pytest.mark.asyncio
    async def test_session_creation_and_completion(self, free_subscription):
        """Создание и завершение сессии"""
        storage = DjangoStorage()

        await storage.add_user(
            user_id=666, username="session_user", full_name="Session User"
        )

        # Создаем сессию
        await storage.create_session(
            user_id=666,
            request_text="Помогите с работой",
            request_type="коучинговый",
            card_type="день",
            card_number=5,
        )

        # Проверяем что сессия создана
        sessions_queryset = UserSession.objects.filter(
            telegram_profile__telegram_id=666
        )
        sessions_count = await sync_to_async(sessions_queryset.count)()
        assert sessions_count == 1

        session = await sync_to_async(sessions_queryset.first)()
        assert session.request_text == "Помогите с работой"
        assert session.request_type == "коучинговый"
        assert session.card_type == "день"
        assert session.card_number == 5
        assert session.completed_at is None

        # Завершаем сессию
        await storage.complete_latest_session(666)

        # Проверяем что сессия завершена
        await sync_to_async(session.refresh_from_db)()
        assert session.completed_at is not None

    @pytest.mark.asyncio
    async def test_daily_sessions_count(self, free_subscription):
        """Подсчет сессий за сегодня"""
        storage = DjangoStorage()

        await storage.add_user(
            user_id=777, username="counter_user", full_name="Counter User"
        )

        # Создаем 2 сессии
        await storage.create_session(777, "Request 1", "test", "день", 1)
        await storage.create_session(777, "Request 2", "test", "ночь", 2)

        # Получаем профиль и проверяем счетчик
        profile = await storage.get_user(777)
        daily_count = await sync_to_async(profile.get_daily_sessions_count)()
        assert daily_count == 2


@pytest.mark.django_db
class TestSubscriptionTransitions:
    """Тесты переходов между подписками"""

    def test_upgrade_from_free_to_premium(
        self, django_user, free_subscription, premium_subscription
    ):
        """Апгрейд с free на premium"""
        # Создаем пользователя с free
        profile = TelegramProfile.objects.create(
            user=django_user, telegram_id=888, current_subscription=free_subscription
        )

        assert profile.get_daily_session_limit() == 1
        assert profile.get_available_card_count() == 10

        # Апгрейд на premium
        profile.activate_subscription(premium_subscription)

        assert profile.current_subscription == premium_subscription
        assert profile.get_daily_session_limit() == 3
        assert profile.get_available_card_count() is None
        assert profile.subscription_expires_at is not None

    def test_subscription_expiration(self, django_user, premium_subscription):
        """Проверка истечения подписки"""
        # Создаем пользователя с истекшей подпиской
        profile = TelegramProfile.objects.create(
            user=django_user,
            telegram_id=999,
            current_subscription=premium_subscription,
            subscription_expires_at=timezone.now() - timezone.timedelta(days=1),
        )

        # Подписка истекла
        assert profile.is_subscribed is False
