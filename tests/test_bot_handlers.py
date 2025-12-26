from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.types import Chat, Message, User

from bot.services.bot_handlers import MacBot


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
