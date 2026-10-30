from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Chat, Message, User
from django.utils import timezone

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

            assert "подписк" in message_text.lower()


def make_command(args):
    command = MagicMock(spec=CommandObject)
    command.args = args
    return command


class TestParseDays:
    @pytest.mark.parametrize(
        "args, expected",
        [(None, 7), ("1", 1), ("30", 30), (" 14 ", 14), ("0", None), ("31", None),
         ("abc", None), ("-5", None)],
    )
    def test_parse_days(self, args, expected):
        assert MacBot._parse_days(make_command(args)) == expected


class TestWaitingStep:
    def test_next_step_after_answered(self):
        assert MacBot._waiting_step("work_3") == "work_4"
        assert MacBot._waiting_step("work_1") == "work_2"

    def test_no_state_waits_for_request(self):
        assert MacBot._waiting_step(None) == "get_request"

    def test_last_and_unknown_steps_kept(self):
        assert MacBot._waiting_step("work_finish") == "work_finish"
        assert MacBot._waiting_step("legacy") == "legacy"


def stats_data(**overrides):
    period = {"new_users": 3, "active_users": 2, "started": 4, "completed": 1}
    data = {
        "days": 7,
        "current": period,
        "previous": {"new_users": 1, "active_users": 1, "started": 2, "completed": 2},
        "stuck": {"work_3": 2, "work_1": 1},
        "abandoned_payments": 5,
        "total_users": 62,
        "total_sessions": 140,
        "total_completed": 46,
    }
    data.update(overrides)
    return data


class TestFormatStats:
    def test_format_stats(self):
        text = MacBot._format_stats(stats_data())
        assert "за 7 дн." in text
        assert "Новых: 3 (1)" in text
        assert "Завершено: 1 (2) — 25%" in text
        assert "Описание приятного персонажа: 2" in text
        assert "Описание чувств и эмоций от карты: 1" in text
        assert "Брошенные оплаты:</b> 5" in text
        assert "сессий 140, завершено 46 — 33%" in text

    def test_format_stats_empty(self):
        empty = {"new_users": 0, "active_users": 0, "started": 0, "completed": 0}
        text = MacBot._format_stats(
            stats_data(current=empty, previous=empty, stuck={}, total_sessions=0)
        )
        assert "Бросили на шаге" not in text
        assert "%" not in text


class TestFormatUsers:
    def user(self, **overrides):
        data = {
            "telegram_id": 42,
            "username": "anna",
            "first_name": "Анна <b>",
            "last_seen": timezone.now(),
            "is_new": True,
            "is_paid": True,
            "started": 2,
            "completed": 1,
            "last_state": "work_3",
        }
        data.update(overrides)
        return data

    def test_format_users(self):
        text = MacBot._format_users({"days": 7, "total": 1, "users": [self.user()]})
        assert '<a href="tg://user?id=42">Анна &lt;b&gt;</a> @anna' in text
        assert "новый · подписка · сессий 2, завершено 1" in text
        assert "ждём ответа: Описание приятного персонажа" in text
        assert "показаны" not in text

    def test_format_users_finished_and_truncated(self):
        user = self.user(
            first_name="", username=None, is_new=False, is_paid=False,
            started=0, last_state="work_finish",
        )
        text = MacBot._format_users({"days": 30, "total": 25, "users": [user]})
        assert "показаны последние 1" in text
        assert '<a href="tg://user?id=42">42</a> —' in text
        assert "последняя сессия завершена" in text
        assert "сессий" not in text

    def test_format_users_empty(self):
        text = MacBot._format_users({"days": 7, "total": 0, "users": []})
        assert text == "За 7 дн. никто не заходил"


@pytest.mark.asyncio
class TestStaffCommands:
    def make_bot(self, is_staff=True):
        with patch("bot.services.bot_handlers.MacBot._load_config") as config, patch(
            "bot.services.bot_handlers.Bot"
        ), patch("bot.services.bot_handlers.Dispatcher"):
            config.return_value = {"messages_work": [""] * 30}
            bot = MacBot()
        bot.db = MagicMock()
        bot.db.is_staff = AsyncMock(return_value=is_staff)
        bot.db.get_statistics = AsyncMock(return_value=stats_data(days=14))
        bot.db.get_recent_users = AsyncMock(
            return_value={"days": 7, "total": 0, "users": []}
        )
        return bot

    async def test_stats_passes_days(self, mock_message):
        bot = self.make_bot()
        await bot.stats_handler(mock_message, make_command("14"))
        bot.db.get_statistics.assert_awaited_once_with(14)
        assert "за 14 дн." in mock_message.answer.call_args.args[0]

    async def test_stats_rejects_bad_days(self, mock_message):
        bot = self.make_bot()
        await bot.stats_handler(mock_message, make_command("100"))
        bot.db.get_statistics.assert_not_awaited()
        assert "Использование" in mock_message.answer.call_args.args[0]

    async def test_users_default_days(self, mock_message):
        bot = self.make_bot()
        await bot.users_handler(mock_message, make_command(None))
        bot.db.get_recent_users.assert_awaited_once_with(7)

    async def test_non_staff_ignored(self, mock_message):
        bot = self.make_bot(is_staff=False)
        await bot.stats_handler(mock_message, make_command(None))
        await bot.users_handler(mock_message, make_command(None))
        mock_message.answer.assert_not_called()
