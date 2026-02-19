import asyncio
import json
import logging
import os
import random

import yaml
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ContentType, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import (
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)
from asgiref.sync import sync_to_async
from django.conf import settings
from redis.asyncio import Redis

from bot.services.bot_storage import DjangoStorage
from bot.services.payment_token import generate_payment_token

REQUEST_TYPE = ["Психотерапевтический", "Коучинговый"]
CARD_TYPE = ["День", "Ночь"]
YES_NO = ["Да", "Нет"]

CARD_FOLDER = {
    "день": "day",
    "ночь": "night",
}


class MacStates(StatesGroup):
    states_descriptions = {
        "get_request": "Ожидание запроса пользователя",
        "chose_request_type": "Выбор типа запроса (психотерапевтический/коучинговый)",
        "chose_card_type": "Выбор типа карты (день/ночь)",
        "work_1": "Подтверждение готовности начать работу",
        "work_2": "Описание чувств и эмоций от карты",
        "work_3": "Описание того, что видит пользователь на карте",
        "work_4": "Описание приятного персонажа",
        "work_5": "Описание неприятного персонажа",
        "work_6": "Описание чувств персонажей",
        "work_7": "Описание происходящего на карте",
        "work_result": "Ответ на вопрос о сходстве с реальной ситуацией",
        "work_result_2": "Показ всех ответов пользователя",
        "work_result_3": "Чувства",
        "work_result_3_1": "Что могла бы сделать",
        "work_result_4": "Получила подсказку",
        "work_result_5": "Окончание работы и предложение консультации",
        "work_finish": "Завершение работы",
    }

    get_request = State()
    chose_request_type = State()
    chose_card_type = State()

    work_1 = State()
    work_2 = State()
    work_3 = State()
    work_4 = State()
    work_5 = State()
    work_6 = State()
    work_7 = State()
    work_result = State()
    work_result_2 = State()
    work_result_3 = State()
    work_result_3_1 = State()
    work_result_4 = State()
    work_result_5 = State()
    work_finish = State()

    @classmethod
    def get_state_description(cls, state: State) -> str:
        if not state:
            return ""
        state_name = state.state.split(":")[-1] if state.state else "None"
        return cls.states_descriptions.get(state_name) or ""


def make_row_keyboard(items: list[str]) -> ReplyKeyboardMarkup:
    """
    Создаёт реплай-клавиатуру с кнопками в один ряд
    :param items: список текстов для кнопок
    :return: объект реплай-клавиатуры
    """
    row = [KeyboardButton(text=item) for item in items]
    return ReplyKeyboardMarkup(keyboard=[row], resize_keyboard=True)


class MacBot:
    def __init__(self):
        # Загружаем сообщения из config/messages.yaml
        messages_path = settings.BASE_DIR / "config" / "messages.yaml"
        self.messages = self._load_config(str(messages_path))

        # Создаем бота с токеном из settings
        self.bot = Bot(
            token=settings.TELEGRAM_BOT_TOKEN,
            default=DefaultBotProperties(
                parse_mode=ParseMode.HTML,
                protect_content=True,
            ),
        )

        # Создаем storage (Redis или Memory)
        storage = self._create_storage()
        self.dp = Dispatcher(storage=storage)

        # Используем Django ORM вместо SQLAlchemy
        self.db = DjangoStorage()

        self._setup_handlers()

        # Используем логгер из Django settings
        self.logger = logging.getLogger("mac_bot")

    def _create_storage(self) -> BaseStorage:
        """Создает хранилище состояний для бота"""
        # Проверяем, включен ли Redis через переменную окружения
        logger = logging.getLogger("mac_bot")
        use_redis = os.getenv("USE_REDIS", "False").lower() == "true"

        if not use_redis:
            logger.info("Используется MemoryStorage для FSM")
            return MemoryStorage()

        try:
            logger.info(
                f"Подключение к Redis: {settings.REDIS_HOST}:{settings.REDIS_PORT}"
            )
            redis = Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                password=settings.REDIS_PASSWORD,
                decode_responses=True,
            )
            logger.info("RedisStorage успешно инициализирован")
            return RedisStorage(redis=redis)
        except Exception as e:
            logger.error(
                f"Ошибка подключения к Redis: {e}. Переключаемся на MemoryStorage"
            )
            return MemoryStorage()

    async def log_state_change(
        self, user_id: int, username: str, state: State, action: str = "change state to"
    ) -> None:
        description = MacStates.get_state_description(state)
        self.logger.info(
            f"User {username} (ID: {user_id}) {action} state {state.state} ({description})"
        )
        await self.db.add_user_state(user_id, state.state, description)

    @staticmethod
    def _load_config(filename: str) -> dict:
        with open(filename, "r") as file:
            return yaml.safe_load(file)

    def _setup_handlers(self) -> None:
        self.dp.message.register(self.command_start_handler, CommandStart())
        self.dp.message.register(self.send_all_handler, Command("send_all"))
        self.dp.message.register(self.stats_handler, Command("stats"))
        self.dp.message.register(self.subscribe_handler, Command("subscribe"))
        self.dp.message.register(self.oferta_handler, Command("oferta"))
        self.dp.message.register(self.privacy_handler, Command("privacy"))
        self.dp.message.register(
            self.webapp_data_handler, F.content_type == ContentType.WEB_APP_DATA
        )

        self.dp.message.register(self.wait_request, MacStates.get_request)
        self.dp.message.register(
            self.process_request,
            MacStates.chose_request_type,
            F.text.in_(REQUEST_TYPE),
        )
        self.dp.message.register(
            self.process_card_type, MacStates.chose_card_type, F.text.in_(CARD_TYPE)
        )

        self.dp.message.register(self.process_work_1, MacStates.work_1)
        self.dp.message.register(self.process_work_2, MacStates.work_2)
        self.dp.message.register(self.process_work_3, MacStates.work_3)
        self.dp.message.register(self.process_work_4, MacStates.work_4)
        self.dp.message.register(self.process_work_5, MacStates.work_5)
        self.dp.message.register(self.process_work_6, MacStates.work_6)
        self.dp.message.register(self.process_work_7, MacStates.work_7)
        self.dp.message.register(self.process_result, MacStates.work_result)
        self.dp.message.register(self.process_result_2, MacStates.work_result_2)
        self.dp.message.register(self.process_result_3, MacStates.work_result_3)
        self.dp.message.register(self.process_result_3_1, MacStates.work_result_3_1)
        self.dp.message.register(self.process_result_4, MacStates.work_result_4)
        self.dp.message.register(self.process_result_5, MacStates.work_result_5)
        self.dp.message.register(self.process_finish, MacStates.work_finish)

    async def command_start_handler(self, message: Message, state: FSMContext) -> None:
        def get_hour_declension(hours: int) -> str:
            if 11 <= hours % 100 <= 19:
                return "часов"
            elif hours % 10 == 1:
                return "час"
            elif 2 <= hours % 10 <= 4:
                return "часа"
            else:
                return "часов"

        self.logger.info(
            f"New start: {message.from_user.full_name} "
            f"(@{message.from_user.username}, ID: {message.from_user.id})"
        )

        # Создаем/обновляем пользователя
        await self.db.add_user(
            user_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
        )

        # Проверяем лимит сессий (staff пользователи обходят лимит)
        is_staff = await self.db.is_staff(message.from_user.id)
        can_start = await self.db.can_start_session(message.from_user.id)

        if not can_start and not is_staff:
            # Получаем информацию о подписке для сообщения
            profile = await self.db.get_user(message.from_user.id)
            session_limit = (
                await sync_to_async(profile.get_daily_session_limit)() if profile else 1
            )

            self.logger.info(
                f"Session limit reached for {message.from_user.full_name} "
                f"(@{message.from_user.username}, ID: {message.from_user.id})"
            )

            # Сообщение зависит от типа подписки
            current_sub = (
                await sync_to_async(lambda: profile.current_subscription)()
                if profile
                else None
            )
            sub_code = (
                await sync_to_async(lambda: current_sub.code)() if current_sub else None
            )

            if profile and current_sub and sub_code == "free":
                msg = (
                    f"⏳ Вы использовали дневной лимит ({session_limit} сессия).\n\n"
                    f"✨ Хотите больше сессий в день?\n"
                    f"Оформите премиум подписку:\n"
                    f"• 3 сессии в день\n"
                    f"• Все карты (полная колода)\n\n"
                    f"Используйте команду /subscribe для оформления подписки."
                )
            else:
                msg = (
                    f"⏳ Вы использовали дневной лимит ({session_limit} сессии).\n"
                    f"Возвращайтесь завтра!"
                )

            await message.answer(msg, reply_markup=ReplyKeyboardRemove())
            return

        await message.answer(
            self.messages["message_1"], reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(MacStates.get_request)

    async def wait_request(self, message: Message, state: FSMContext) -> None:
        await self.log_state_change(
            message.from_user.id,
            message.from_user.username,
            MacStates.get_request,
        )
        user_request = message.text
        await state.update_data(request=user_request)
        await message.answer(
            self.messages["message_request"],
            reply_markup=make_row_keyboard(REQUEST_TYPE),
        )
        await state.set_state(MacStates.chose_request_type)

    async def process_request(self, message: Message, state: FSMContext) -> None:
        await self.log_state_change(
            message.from_user.id,
            message.from_user.username,
            MacStates.chose_request_type,
        )

        user_request = message.text
        await state.update_data(request_type=user_request.lower())

        await message.answer(self.messages["messages_card"][0])
        await message.answer(self.messages["messages_card"][1])
        await message.answer(
            self.messages["messages_card"][2],
            reply_markup=make_row_keyboard(CARD_TYPE),
        )
        await state.set_state(MacStates.chose_card_type)

    async def process_card_type(self, message: Message, state: FSMContext) -> None:
        await self.log_state_change(
            message.from_user.id, message.from_user.username, MacStates.chose_card_type
        )

        user_card_type = message.text
        await state.update_data(card_type=user_card_type.lower())

        await message.answer(self.messages["messages_work"][0])
        await message.answer(
            self.messages["messages_work"][1],
            reply_markup=make_row_keyboard(["Хорошо, я готов/а"]),
        )
        await state.set_state(MacStates.work_1)

    async def process_work_1(self, message: Message, state: FSMContext) -> None:
        await self.log_state_change(
            message.from_user.id, message.from_user.username, MacStates.work_1
        )

        # Получаем данные из состояния
        data = await state.get_data()
        card_type = data.get("card_type")
        request_text = data.get("request", "")
        request_type = data.get("request_type", "")

        # Получаем лимит карт на основе подписки
        # Free: cards_limit = 10, Premium: cards_limit = None
        cards_limit = await self.db.get_user_cards_limit(message.from_user.id)

        # Путь к папке с картами
        cards_folder = settings.MEDIA_ROOT / "images" / CARD_FOLDER[card_type]

        # Получаем количество доступных карт из файловой системы
        total_cards = len(list(cards_folder.glob("*.jpg")))

        # None = без ограничений (premium), иначе используем лимит
        max_card_number = (
            total_cards if cards_limit is None else min(cards_limit, total_cards)
        )

        image_number = random.randint(1, max_card_number)
        image_name = f"{image_number:05}.jpg"
        image_path = cards_folder / image_name

        # Создаем запись сессии в БД
        await self.db.create_session(
            user_id=message.from_user.id,
            request_text=request_text,
            request_type=request_type,
            card_type=card_type,
            card_number=image_number,
        )

        photo = FSInputFile(str(image_path))
        await message.answer_photo(photo, caption=self.messages["messages_work"][2])
        await message.answer(
            self.messages["messages_work"][3], reply_markup=ReplyKeyboardRemove()
        )

        asyncio.create_task(self.send_reminder(message))

        await state.set_state(MacStates.work_2)

    async def process_work_2(self, message: Message, state: FSMContext) -> None:
        await self.log_state_change(
            message.from_user.id, message.from_user.username, MacStates.work_2
        )
        answer = message.text
        await state.update_data(feelengs=answer)
        await message.answer(self.messages["messages_work"][4])
        await state.set_state(MacStates.work_3)

    async def process_work_3(self, message: Message, state: FSMContext) -> None:
        await self.log_state_change(
            message.from_user.id, message.from_user.username, MacStates.work_3
        )
        answer = message.text
        await state.update_data(views=answer)
        await message.answer(self.messages["messages_work"][5])
        await message.answer(self.messages["messages_work"][6])
        await state.set_state(MacStates.work_4)

    async def process_work_4(self, message: Message, state: FSMContext) -> None:
        await self.log_state_change(
            message.from_user.id, message.from_user.username, MacStates.work_4
        )
        answer = message.text
        await state.update_data(nice_character=answer)
        await message.answer(self.messages["messages_work"][7])
        await message.answer(self.messages["messages_work"][8])
        await message.answer(self.messages["messages_work"][9])
        await state.set_state(MacStates.work_5)

    async def process_work_5(self, message: Message, state: FSMContext) -> None:
        await self.log_state_change(
            message.from_user.id, message.from_user.username, MacStates.work_5
        )
        answer = message.text
        await state.update_data(unlike_character=answer)
        await message.answer(self.messages["messages_work"][10])
        await message.answer(self.messages["messages_work"][11])
        await message.answer(self.messages["messages_work"][12])
        await state.set_state(MacStates.work_6)

    async def process_work_6(self, message: Message, state: FSMContext) -> None:
        await self.log_state_change(
            message.from_user.id, message.from_user.username, MacStates.work_6
        )
        answer = message.text
        await state.update_data(characters_feelings=answer)
        await message.answer(self.messages["messages_work"][13])
        await message.answer(self.messages["messages_work"][14])
        await state.set_state(MacStates.work_7)

    async def process_work_7(self, message: Message, state: FSMContext) -> None:
        await self.log_state_change(
            message.from_user.id, message.from_user.username, MacStates.work_7
        )
        answer = message.text
        await state.update_data(whats_happening=answer)
        await message.answer(self.messages["messages_work"][15])
        await message.answer(self.messages["messages_work"][16])
        await state.set_state(MacStates.work_result)

    async def process_result(self, message: Message, state: FSMContext) -> None:
        await self.log_state_change(
            message.from_user.id, message.from_user.username, MacStates.work_result
        )
        answer = message.text
        await state.update_data(like_this=answer)
        await message.answer(self.messages["messages_work"][17])
        await message.answer(self.messages["messages_work"][18])
        await message.answer(
            self.messages["messages_work"][19],
            reply_markup=make_row_keyboard(["OK"]),
        )
        await state.set_state(MacStates.work_result_2)

    async def process_result_2(self, message: Message, state: FSMContext) -> None:
        await self.log_state_change(
            message.from_user.id, message.from_user.username, MacStates.work_result_2
        )
        data = await state.get_data()
        await message.answer(
            self.messages["messages_work"][20], reply_markup=ReplyKeyboardRemove()
        )
        for key in [
            "request",
            "feelengs",
            "views",
            "nice_character",
            "unlike_character",
            "characters_feelings",
            "whats_happening",
            "like_this",
        ]:
            if data.get(key):
                await message.answer(data[key])
        await message.answer(
            self.messages["messages_work"][21], reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(MacStates.work_result_3)

    async def process_result_3(self, message: Message, state: FSMContext) -> None:
        await self.log_state_change(
            message.from_user.id, message.from_user.username, MacStates.work_result_3
        )
        await message.answer(self.messages["messages_work"][22])
        await state.set_state(MacStates.work_result_3_1)

    async def process_result_3_1(self, message: Message, state: FSMContext) -> None:
        await self.log_state_change(
            message.from_user.id, message.from_user.username, MacStates.work_result_3_1
        )
        await message.answer(self.messages["messages_work"][23])
        await state.set_state(MacStates.work_result_4)

    async def process_result_4(self, message: Message, state: FSMContext) -> None:
        await self.log_state_change(
            message.from_user.id, message.from_user.username, MacStates.work_result_4
        )
        await message.answer(
            self.messages["messages_work"][24],
            reply_markup=make_row_keyboard(YES_NO),
        )
        await state.set_state(MacStates.work_result_5)

    async def process_result_5(self, message: Message, state: FSMContext) -> None:
        await self.log_state_change(
            message.from_user.id, message.from_user.username, MacStates.work_result_5
        )
        data = await state.get_data()
        if "да" in message.text.lower():
            await message.answer(
                self.messages["messages_work"][25], reply_markup=ReplyKeyboardRemove()
            )
        else:
            await message.answer(
                self.messages["messages_work"][26], reply_markup=ReplyKeyboardRemove()
            )
        encouragement_words = self.messages["encouragement_words"]
        await message.answer(random.choice(encouragement_words))
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Записаться на консультацию",
                        url=f"https://t.me/{settings.MASTER_NAME}",
                    )
                ]
            ]
        )
        await message.answer(self.messages["messages_work"][27], reply_markup=keyboard)

        # Завершаем сессию в БД
        await self.db.complete_latest_session(message.from_user.id)

        await self.log_state_change(
            message.from_user.id, message.from_user.username, MacStates.work_finish
        )

    async def process_finish(self, message: Message, state: FSMContext) -> None: ...

    async def send_reminder(self, message: Message) -> None:
        await asyncio.sleep(24 * 60 * 60)  # Ждём 24 часа
        full_name = message.from_user.full_name
        username = message.from_user.username
        user_id = message.from_user.id
        try:
            await message.answer(
                "Готов/а вытянуть новую карту и получить подсказку на сегодня? Нажми /start",
                reply_markup=ReplyKeyboardRemove(),
            )
            self.logger.info(f"Send reminder: {full_name} (@{username}, ID: {user_id})")
        except Exception as e:
            self.logger.error(
                f"Failed to send reminder to user: {full_name} (@{username}, ID: {user_id}): {e}"
            )

    async def send_all_handler(self, message: Message) -> None:
        if not await self.db.is_staff(message.from_user.id):
            await message.answer("У вас нет прав для выполнения этой команды")
            return

        if not isinstance(self.dp.storage, RedisStorage):
            await message.answer("Redis storage is not available")
            return

        redis = self.dp.storage.redis
        keys = await redis.keys("fsm:*:data")

        sent_count = 0
        failed_count = 0

        for key in keys:
            try:
                user_data = await redis.get(key)
                if user_data:
                    # Извлекаем ID пользователя из ключа (формат: fsm:user_id:data)
                    user_id = key.split(":")[1]
                    await self.bot.send_message(
                        chat_id=user_id,
                        text="Готов/а вытянуть новую карту и получить подсказку на сегодня? "
                        "Нажми /start",
                    )
                    sent_count += 1
            except Exception as e:
                self.logger.error(f"Не удалось отправить сообщение пользователю: {e}")
                failed_count += 1

        await message.answer(
            f"Сообщения отправлены: {sent_count}\nОшибки отправки: {failed_count}"
        )

    async def stats_handler(self, message: Message) -> None:
        if not await self.db.is_staff(message.from_user.id):
            return

        try:
            stats = await self.db.get_statistics()

            stats_text = f"""📊 <b>Статистика бота</b>
👥 <b>Пользователи:</b>
• Всего: {stats['total_users']}
• За последние 7 дней: {stats['recent_users']}
• Завершенных сессий: {stats['completed_sessions']}"""
            await message.answer(stats_text)

        except Exception as e:
            self.logger.error(f"Ошибка получения статистики: {e}")
            await message.answer("Произошла ошибка при получении статистики")

    async def subscribe_handler(self, message: Message) -> None:
        """Обработчик команды /subscribe - показывает информацию о подписке"""
        user_id = message.from_user.id
        username = message.from_user.username or "Unknown"

        self.logger.info(
            f"[SUBSCRIBE] User {user_id} (@{username}) called /subscribe command"
        )

        try:
            # Получаем профиль пользователя
            self.logger.info(f"[SUBSCRIBE] Getting user profile for {user_id}")
            profile = await self.db.get_user(user_id)

            if not profile:
                await message.answer("Ошибка: профиль не найден. Используйте /start")
                return

            current_sub = await sync_to_async(lambda: profile.current_subscription)()
            sub_code = await sync_to_async(
                lambda: current_sub.code if current_sub else None
            )()
            is_premium = current_sub and sub_code != "free"

            if is_premium:
                expires_at = await sync_to_async(
                    lambda: profile.subscription_expires_at
                )()
                if expires_at:
                    # Пользователь уже premium
                    expires_date = expires_at.strftime("%d.%m.%Y")
                    sub_name = await sync_to_async(lambda: current_sub.name)()
                    sub_price = await sync_to_async(lambda: current_sub.price)()
                    daily_limit = await sync_to_async(
                        lambda: current_sub.daily_sessions_limit
                    )()
                    cards_limit = await sync_to_async(lambda: current_sub.cards_limit)()
                    cards_text = (
                        "Все 81 карта" if cards_limit is None else f"{cards_limit} карт"
                    )

                    msg = f"""✨ <b>Ваша подписка</b>

📋 Тариф: <b>{sub_name}</b>
💰 Стоимость: {sub_price}₽
📅 Действует до: <b>{expires_date}</b>

⚡️ Доступные возможности:
• {daily_limit} сессии в день
• {cards_text} (полная колода)

Для продления подписки выберите тариф ниже."""
                else:
                    is_premium = False

            if not is_premium:
                # Free пользователь
                msg = """Выберите тариф:

💳 Месячная - 300₽
💎 Годовая - 3000₽ (-17%)

✨ 3 сессии/день • Все 81 карта"""

            # Генерируем токен для защищенной ссылки на страницу подписки
            token = generate_payment_token(user_id, username)
            info_url = f"{settings.BASE_URL}/subscription/info/{token}/"

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Управление подпиской", url=info_url)]
                ]
            )

            self.logger.info(
                f"[SUBSCRIBE] Sending subscription options to user {user_id}"
            )

            result = await message.answer(msg, reply_markup=keyboard)

            self.logger.info(
                f"[SUBSCRIBE] Successfully sent subscription info to user {user_id}, message_id: {result.message_id}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка в subscribe_handler: {e}")
            await message.answer("Произошла ошибка. Попробуйте позже.")

    async def webapp_data_handler(self, message: Message) -> None:
        """Обработчик данных из WebApp - обработка выбора тарифа"""
        user_id = message.from_user.id
        username = message.from_user.username

        self.logger.info(
            f"[WEBAPP] Received WebApp data from user {user_id} (@{username})"
        )

        try:
            # Парсим данные из WebApp
            raw_data = message.web_app_data.data
            self.logger.info(f"[WEBAPP] Raw data: {raw_data}")

            data = json.loads(raw_data)
            self.logger.info(f"[WEBAPP] Parsed data: {data}")

            plan_code = data.get("plan")
            self.logger.info(f"[WEBAPP] Plan code: {plan_code}")

            if not plan_code:
                self.logger.error(f"[WEBAPP] No plan code in data: {data}")
                await message.answer("❌ Ошибка: тариф не выбран")
                return

            self.logger.info(
                f"[WEBAPP] User {username} ({user_id}) selected plan: {plan_code}"
            )

            # Создаем заказ на оплату
            self.logger.info(f"[WEBAPP] Creating payment order...")
            order_id, payment_url = await self.db.create_payment_order(
                user_id=user_id, plan_code=plan_code, username=username
            )
            self.logger.info(
                f"[WEBAPP] Payment order created: {order_id}, URL: {payment_url[:50]}..."
            )

            # Отправляем ссылку на оплату
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Перейти к оплате", url=payment_url)]
                ]
            )

            plan_names = {
                "monthly": "Месячная премиум (300₽)",
                "yearly": "Годовая премиум (3000₽)",
            }
            plan_name = plan_names.get(plan_code, plan_code)

            await message.answer(
                f"✨ <b>Оформление подписки</b>\n\n"
                f"📋 Тариф: <b>{plan_name}</b>\n"
                f"🔢 Заказ: <code>{order_id}</code>\n\n"
                f"Нажмите кнопку ниже для оплаты:",
                reply_markup=keyboard,
            )

        except ValueError as e:
            self.logger.error(f"ValueError in webapp_data_handler: {e}")
            await message.answer(f"❌ Ошибка: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error in webapp_data_handler: {e}")
            await message.answer(
                "❌ Произошла ошибка при создании заказа. Попробуйте позже."
            )

    async def oferta_handler(self, message: Message) -> None:
        """Обработчик команды /oferta - открывает публичную оферту"""
        try:
            base_url = settings.BASE_URL or "https://mac.eremenko.live"
            oferta_url = f"{base_url}/static/oferta.html"

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="📄 Открыть оферту", web_app=WebAppInfo(url=oferta_url)
                        )
                    ]
                ]
            )

            await message.answer("📋 <b>Публичная оферта</b>", reply_markup=keyboard)

        except Exception as e:
            self.logger.error(f"Error in oferta_handler: {e}")
            await message.answer("❌ Произошла ошибка. Попробуйте позже.")

    async def privacy_handler(self, message: Message) -> None:
        """Обработчик команды /privacy - открывает политику конфиденциальности"""
        try:
            base_url = settings.BASE_URL or "https://mac.eremenko.live"
            privacy_url = f"{base_url}/static/privacy.html"

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔒 Открыть политику",
                            web_app=WebAppInfo(url=privacy_url),
                        )
                    ]
                ]
            )

            await message.answer(
                "🔒 <b>Политика конфиденциальности</b>", reply_markup=keyboard
            )

        except Exception as e:
            self.logger.error(f"Error in privacy_handler: {e}")
            await message.answer("❌ Произошла ошибка. Попробуйте позже.")

    async def start(self) -> None:
        """Запуск бота"""
        await self.db.init_db()
        self.logger.info("Бот запущен")
        await self.dp.start_polling(self.bot)
