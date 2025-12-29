import pytest
from django.conf import settings

from bot.services.prodamus_service import ProdamusService


@pytest.mark.django_db
class TestProdamusServiceInit:
    """Тесты инициализации ProdamusService"""

    def test_init_with_settings(self):
        """Проверка инициализации с настройками из settings"""
        service = ProdamusService()
        assert service.merchant_url == settings.PRODAMUS_MERCHANT_URL
        assert service.test_mode == settings.PRODAMUS_TEST_MODE

        # Проверяем что создан ProdamusPy объект
        assert hasattr(service, "prodamus_py")
        assert service.prodamus_py is not None

        # Проверяем что подпись работает (косвенная проверка корректности secret key)
        test_data = {"test": "data"}
        signature = service.generate_signature(test_data)
        assert len(signature) == 64  # SHA256 hex подпись всегда 64 символа


@pytest.mark.django_db
class TestGenerateOrderId:
    """Тесты генерации order_id"""

    def test_generate_order_id_format(self):
        """Проверка формата генерируемого order_id"""
        service = ProdamusService()
        order_id = service.generate_order_id(12345, "monthly")

        assert order_id.startswith("ORDER_12345_monthly_")
        assert len(order_id.split("_")) == 4
        # UUID часть должна быть 8 символов
        uuid_part = order_id.split("_")[-1]
        assert len(uuid_part) == 8

    def test_generate_order_id_uniqueness(self):
        """Проверка уникальности генерируемых order_id"""
        service = ProdamusService()
        order_id_1 = service.generate_order_id(12345, "monthly")
        order_id_2 = service.generate_order_id(12345, "monthly")

        assert order_id_1 != order_id_2

    def test_generate_order_id_different_users(self):
        """Проверка генерации для разных пользователей"""
        service = ProdamusService()
        order_id_1 = service.generate_order_id(111, "monthly")
        order_id_2 = service.generate_order_id(222, "monthly")

        assert "ORDER_111_" in order_id_1
        assert "ORDER_222_" in order_id_2


@pytest.mark.django_db
class TestGenerateSignature:
    """Тесты генерации HMAC SHA256 подписи"""

    def test_generate_signature_basic(self):
        """Проверка базовой генерации подписи"""
        service = ProdamusService()
        data = {"order_id": "123", "amount": "300"}
        signature = service.generate_signature(data)

        # SHA256 hex подпись всегда 64 символа
        assert len(signature) == 64
        assert isinstance(signature, str)

    def test_generate_signature_deterministic(self):
        """Проверка детерминированности подписи"""
        service = ProdamusService()
        data = {"order_id": "123", "amount": "300"}

        signature_1 = service.generate_signature(data)
        signature_2 = service.generate_signature(data)

        assert signature_1 == signature_2

    def test_generate_signature_different_data(self):
        """Проверка разных подписей для разных данных"""
        service = ProdamusService()
        data_1 = {"order_id": "123", "amount": "300"}
        data_2 = {"order_id": "456", "amount": "300"}

        signature_1 = service.generate_signature(data_1)
        signature_2 = service.generate_signature(data_2)

        assert signature_1 != signature_2

    def test_generate_signature_sorted_params(self):
        """Проверка сортировки параметров"""
        service = ProdamusService()
        # Параметры в разном порядке должны давать одинаковую подпись
        data_1 = {"b": "2", "a": "1", "c": "3"}
        data_2 = {"a": "1", "c": "3", "b": "2"}

        signature_1 = service.generate_signature(data_1)
        signature_2 = service.generate_signature(data_2)

        assert signature_1 == signature_2


@pytest.mark.django_db
class TestVerifyWebhookSignature:
    """Тесты проверки подписи webhook"""

    def test_verify_valid_signature(self):
        """Проверка валидной подписи"""
        service = ProdamusService()
        data = {"order_id": "123", "amount": "300"}
        signature = service.generate_signature(data)

        is_valid = service.verify_webhook_signature(data, signature)
        assert is_valid is True

    def test_verify_invalid_signature(self):
        """Проверка невалидной подписи"""
        service = ProdamusService()
        data = {"order_id": "123", "amount": "300"}
        invalid_signature = "invalid_signature_12345"

        is_valid = service.verify_webhook_signature(data, invalid_signature)
        assert is_valid is False

    def test_verify_signature_ignores_signature_field(self):
        """Проверка что поле signature игнорируется при проверке"""
        service = ProdamusService()
        data = {"order_id": "123", "amount": "300"}
        signature = service.generate_signature(data)

        # Добавляем signature в данные
        data_with_signature = {**data, "signature": signature}

        is_valid = service.verify_webhook_signature(data_with_signature, signature)
        assert is_valid is True


@pytest.mark.django_db
class TestGetSubscriptionByCode:
    """Тесты получения подписки из БД"""

    def test_get_existing_subscription(self, free_subscription):
        """Проверка получения существующей подписки"""
        service = ProdamusService()
        subscription = service.get_subscription_by_code("free")

        assert subscription is not None
        assert subscription.code == "free"
        assert subscription.name == "Бесплатный"

    def test_get_nonexistent_subscription(self):
        """Проверка получения несуществующей подписки"""
        service = ProdamusService()
        subscription = service.get_subscription_by_code("nonexistent")

        assert subscription is None

    def test_get_inactive_subscription(self, free_subscription):
        """Проверка что неактивные подписки не возвращаются"""
        service = ProdamusService()

        # Деактивируем подписку
        free_subscription.is_active = False
        free_subscription.save()

        subscription = service.get_subscription_by_code("free")
        assert subscription is None


@pytest.mark.django_db
@pytest.mark.asyncio
class TestCreatePaymentLink:
    """Тесты создания платежной ссылки"""

    async def test_create_payment_link_basic(self, premium_subscription):
        """Проверка базового создания платежной ссылки"""
        from unittest.mock import AsyncMock, MagicMock, patch

        service = ProdamusService()
        order_id = "ORDER_123_monthly_abc"

        # Мокаем ответ Prodamus (возвращает plain text URL)
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value="https://payform.ru/test12345/")
        mock_response.headers = {}

        # Создаем мок для async context manager
        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session_instance = MagicMock()
        mock_session_instance.post = MagicMock(return_value=mock_post_cm)
        mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
        mock_session_instance.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "bot.services.prodamus_service.aiohttp.ClientSession",
            return_value=mock_session_instance,
        ):
            url = await service.create_payment_link(
                order_id=order_id, subscription_plan=premium_subscription, user_id=12345
            )

        # Проверяем что получили URL от Prodamus
        assert url == "https://payform.ru/test12345/"
        assert url.startswith("https://")

    async def test_create_payment_link_with_username(self, premium_subscription):
        """Проверка создания ссылки с username"""
        from unittest.mock import AsyncMock, MagicMock, patch

        service = ProdamusService()
        order_id = "ORDER_123_monthly_abc"

        # Мокаем ответ Prodamus
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value="https://payform.ru/testuser/")
        mock_response.headers = {}

        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session_instance = MagicMock()
        mock_session_instance.post = MagicMock(return_value=mock_post_cm)
        mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
        mock_session_instance.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "bot.services.prodamus_service.aiohttp.ClientSession",
            return_value=mock_session_instance,
        ):
            url = await service.create_payment_link(
                order_id=order_id,
                subscription_plan=premium_subscription,
                user_id=12345,
                username="test_user",
            )

        # Проверяем что получили URL
        assert url.startswith("https://")

    async def test_create_payment_link_test_mode(self, premium_subscription):
        """Проверка создания ссылки в тестовом режиме"""
        from unittest.mock import AsyncMock, MagicMock, patch

        service = ProdamusService()
        service.test_mode = True
        order_id = "ORDER_123_monthly_abc"

        # Мокаем ответ Prodamus
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value="https://payform.ru/testmode/")
        mock_response.headers = {}

        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session_instance = MagicMock()
        mock_session_instance.post = MagicMock(return_value=mock_post_cm)
        mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
        mock_session_instance.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "bot.services.prodamus_service.aiohttp.ClientSession",
            return_value=mock_session_instance,
        ):
            url = await service.create_payment_link(
                order_id=order_id, subscription_plan=premium_subscription, user_id=12345
            )

        # Проверяем что получили URL
        assert url.startswith("https://")

    async def test_create_payment_link_returns_valid_url(self, premium_subscription):
        """Проверка что метод возвращает валидный URL"""
        from unittest.mock import AsyncMock, MagicMock, patch

        service = ProdamusService()
        order_id = "ORDER_123_monthly_abc"

        # Мокаем ответ Prodamus
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value="https://payform.ru/abc123/")
        mock_response.headers = {}

        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session_instance = MagicMock()
        mock_session_instance.post = MagicMock(return_value=mock_post_cm)
        mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
        mock_session_instance.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "bot.services.prodamus_service.aiohttp.ClientSession",
            return_value=mock_session_instance,
        ):
            url = await service.create_payment_link(
                order_id=order_id, subscription_plan=premium_subscription, user_id=12345
            )

        # Проверяем что URL валиден
        assert isinstance(url, str)
        assert url.startswith("https://")
        assert len(url) > 10


@pytest.mark.django_db
class TestGetPlanInfo:
    """Тесты получения информации о тарифе"""

    def test_get_plan_info_existing(self, premium_subscription):
        """Проверка получения информации о существующем тарифе"""
        service = ProdamusService()
        plan_info = service.get_plan_info("monthly")

        assert plan_info is not None
        assert plan_info["name"] == "Премиум"
        assert plan_info["code"] == "monthly"
        assert plan_info["price"] == 300.0
        assert plan_info["duration_days"] == 30
        assert plan_info["daily_sessions_limit"] == 3
        assert plan_info["cards_limit"] is None

    def test_get_plan_info_nonexistent(self):
        """Проверка получения информации о несуществующем тарифе"""
        service = ProdamusService()
        plan_info = service.get_plan_info("nonexistent")

        assert plan_info is None

    def test_get_plan_info_free(self, free_subscription):
        """Проверка получения информации о бесплатном тарифе"""
        service = ProdamusService()
        plan_info = service.get_plan_info("free")

        assert plan_info is not None
        assert plan_info["price"] == 0.0
        assert plan_info["daily_sessions_limit"] == 1
        assert plan_info["cards_limit"] == 10
