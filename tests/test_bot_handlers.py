from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.types import Chat, Message, User

from bot.services.bot_handlers import MacBot
from bot.services.payment_token import validate_payment_token


@pytest.fixture
def mock_message():
    """Создает мок объект Message"""
    message = MagicMock(spec=Message)
    message.from_user = MagicMock(spec=User)
    message.from_user.id = 123456789
    message.from_user.username = "test_user"
    message.chat = MagicMock(spec=Chat)
    message.chat.id = 123456789
    message.answer = AsyncMock()
    return message


@pytest.fixture
def mock_state():
    """Создает мок объект FSMContext"""
    state = MagicMock(spec=FSMContext)
    state.get_data = AsyncMock()
    state.set_state = AsyncMock()
    return state


@pytest.mark.asyncio
class TestProcessResult2Handler:
    """Тесты для обработчика process_result_2"""

    async def test_process_result_2_with_valid_data(self, mock_message, mock_state):
        """Тест: все поля заполнены корректно"""
        # Arrange
        mock_state.get_data.return_value = {
            "request": "Мой запрос",
            "feelengs": "Чувства",
            "views": "Что вижу",
            "nice_character": "Приятный персонаж",
            "unlike_character": "Неприятный персонаж",
            "characters_feelings": "Чувства персонажей",
            "whats_happening": "Что происходит",
            "like_this": "Нравится это",
        }

        with patch(
            "bot.services.bot_handlers.MacBot._load_config"
        ) as mock_config, patch(
            "bot.services.bot_handlers.MacBot.log_state_change", new_callable=AsyncMock
        ), patch(
            "bot.services.bot_handlers.Bot"
        ), patch(
            "bot.services.bot_handlers.Dispatcher"
        ):
            mock_config.return_value = {
                "messages_work": [""] * 30  # Заполняем пустыми строками
            }
            bot = MacBot()

            # Act
            await bot.process_result_2(mock_message, mock_state)

            # Assert
            assert mock_state.get_data.called
            # Должно быть отправлено 8 сообщений + 2 системных
            assert mock_message.answer.call_count == 10

    async def test_process_result_2_with_none_values(self, mock_message, mock_state):
        """Тест: некоторые поля имеют значение None - не должно быть ошибки"""
        # Arrange
        mock_state.get_data.return_value = {
            "request": "Мой запрос",
            "feelengs": None,  # None значение
            "views": "Что вижу",
            "nice_character": None,  # None значение
            "unlike_character": "Неприятный персонаж",
            "characters_feelings": None,  # None значение
            "whats_happening": "Что происходит",
            "like_this": "",  # Пустая строка
        }

        with patch(
            "bot.services.bot_handlers.MacBot._load_config"
        ) as mock_config, patch(
            "bot.services.bot_handlers.MacBot.log_state_change", new_callable=AsyncMock
        ), patch(
            "bot.services.bot_handlers.Bot"
        ), patch(
            "bot.services.bot_handlers.Dispatcher"
        ):
            mock_config.return_value = {"messages_work": [""] * 30}
            bot = MacBot()

            # Act - не должно быть ValidationError
            await bot.process_result_2(mock_message, mock_state)

            # Assert
            assert mock_state.get_data.called
            # Должно быть отправлено только 4 непустых значения + 2 системных
            assert mock_message.answer.call_count == 6

    async def test_process_result_2_with_all_none(self, mock_message, mock_state):
        """Тест: все поля None - должны отправиться только системные сообщения"""
        # Arrange
        mock_state.get_data.return_value = {
            "request": None,
            "feelengs": None,
            "views": None,
            "nice_character": None,
            "unlike_character": None,
            "characters_feelings": None,
            "whats_happening": None,
            "like_this": None,
        }

        with patch(
            "bot.services.bot_handlers.MacBot._load_config"
        ) as mock_config, patch(
            "bot.services.bot_handlers.MacBot.log_state_change", new_callable=AsyncMock
        ), patch(
            "bot.services.bot_handlers.Bot"
        ), patch(
            "bot.services.bot_handlers.Dispatcher"
        ):
            mock_config.return_value = {"messages_work": [""] * 30}
            bot = MacBot()

            # Act
            await bot.process_result_2(mock_message, mock_state)

            # Assert
            assert mock_state.get_data.called
            # Должно быть отправлено только 2 системных сообщения
            assert mock_message.answer.call_count == 2

    async def test_process_result_2_with_missing_keys(self, mock_message, mock_state):
        """Тест: некоторые ключи отсутствуют в data - не должно быть ошибки"""
        # Arrange
        mock_state.get_data.return_value = {
            "request": "Мой запрос",
            "views": "Что вижу",
            # Остальные ключи отсутствуют
        }

        with patch(
            "bot.services.bot_handlers.MacBot._load_config"
        ) as mock_config, patch(
            "bot.services.bot_handlers.MacBot.log_state_change", new_callable=AsyncMock
        ), patch(
            "bot.services.bot_handlers.Bot"
        ), patch(
            "bot.services.bot_handlers.Dispatcher"
        ):
            mock_config.return_value = {"messages_work": [""] * 30}
            bot = MacBot()

            # Act
            await bot.process_result_2(mock_message, mock_state)

            # Assert
            assert mock_state.get_data.called
            # Должно быть отправлено 2 непустых значения + 2 системных
            assert mock_message.answer.call_count == 4


@pytest.mark.asyncio
class TestSubscribeHandler:
    """Тесты для обработчика /subscribe"""

    async def test_subscribe_handler_uses_url_not_webapp(
        self, mock_message, mock_state
    ):
        """Проверяем что используется URL кнопка, а не WebApp"""
        with patch(
            "bot.services.bot_handlers.MacBot._load_config"
        ) as mock_config, patch("bot.services.bot_handlers.Bot"), patch(
            "bot.services.bot_handlers.Dispatcher"
        ):
            mock_config.return_value = {"messages_work": [""] * 30}

            # Мокаем db.get_user чтобы вернуть профиль без подписки
            bot = MacBot()
            bot.db = MagicMock()
            bot.db.get_user = AsyncMock(
                return_value=MagicMock(current_subscription=None, is_subscribed=False)
            )

            await bot.subscribe_handler(mock_message)

            # Проверяем что answer был вызван
            assert mock_message.answer.called

            # Получаем аргументы вызова
            call_kwargs = mock_message.answer.call_args
            reply_markup = call_kwargs.kwargs.get("reply_markup")

            assert reply_markup is not None

            # Проверяем первую кнопку - должна быть URL, а не WebApp
            first_button = reply_markup.inline_keyboard[0][0]
            assert first_button.url is not None
            assert first_button.web_app is None
            assert "/subscription/info/" in first_button.url

    async def test_subscribe_handler_url_contains_valid_token(
        self, mock_message, mock_state
    ):
        """Проверяем что URL содержит валидный токен"""
        with patch(
            "bot.services.bot_handlers.MacBot._load_config"
        ) as mock_config, patch("bot.services.bot_handlers.Bot"), patch(
            "bot.services.bot_handlers.Dispatcher"
        ):
            mock_config.return_value = {"messages_work": [""] * 30}

            bot = MacBot()
            bot.db = MagicMock()
            bot.db.get_user = AsyncMock(
                return_value=MagicMock(current_subscription=None, is_subscribed=False)
            )

            await bot.subscribe_handler(mock_message)

            # Получаем URL из кнопки
            call_kwargs = mock_message.answer.call_args
            reply_markup = call_kwargs.kwargs.get("reply_markup")
            first_button = reply_markup.inline_keyboard[0][0]
            url = first_button.url

            # Извлекаем токен из URL
            # URL формат: {BASE_URL}/subscription/info/{token}/
            token = url.split("/subscription/info/")[1].rstrip("/")

            # Валидируем токен
            data = validate_payment_token(token)
            assert data is not None
            assert data["telegram_id"] == mock_message.from_user.id
            assert data["username"] == mock_message.from_user.username

    async def test_subscribe_handler_with_premium_user(self, mock_message, mock_state):
        """Проверяем что премиум пользователь видит информацию о подписке"""
        from datetime import timedelta
        from django.utils import timezone

        with patch(
            "bot.services.bot_handlers.MacBot._load_config"
        ) as mock_config, patch("bot.services.bot_handlers.Bot"), patch(
            "bot.services.bot_handlers.Dispatcher"
        ):
            mock_config.return_value = {"messages_work": [""] * 30}

            # Создаем мок премиум подписки
            mock_subscription = MagicMock()
            mock_subscription.code = "monthly"
            mock_subscription.name = "Премиум"
            mock_subscription.price = 300
            mock_subscription.daily_sessions_limit = 3
            mock_subscription.cards_limit = None

            mock_profile = MagicMock()
            mock_profile.current_subscription = mock_subscription
            mock_profile.is_subscribed = True
            mock_profile.subscription_expires_at = timezone.now() + timedelta(days=30)

            bot = MacBot()
            bot.db = MagicMock()
            bot.db.get_user = AsyncMock(return_value=mock_profile)

            await bot.subscribe_handler(mock_message)

            # Проверяем что сообщение содержит информацию о подписке
            call_args = mock_message.answer.call_args
            message_text = (
                call_args.args[0]
                if call_args.args
                else call_args.kwargs.get("text", "")
            )

            assert "Премиум" in message_text or "подписка" in message_text.lower()
