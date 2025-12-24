import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth.models import User as DjangoUser

from bot.models import StateType, TelegramProfile, UserState


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestDjangoStorageAddUser:
    """Тесты для DjangoStorage.add_user"""

    async def test_add_new_user(self, storage, free_subscription):
        """Создание нового пользователя"""
        await storage.add_user(
            user_id=123456789,
            username="new_user",
            full_name="New User"
        )
        django_user = await sync_to_async(DjangoUser.objects.get)(username="tg_123456789")
        assert django_user.first_name == "New User"
        profile = await sync_to_async(TelegramProfile.objects.get)(telegram_id=123456789)
        assert profile.username == "new_user"
        assert profile.first_name == "New User"

    async def test_add_user_with_long_name(self, storage, free_subscription):
        """Имя обрезается до 30 символов для Django User"""
        long_name = "A" * 50
        await storage.add_user(
            user_id=111222333,
            username="long_name_user",
            full_name=long_name
        )
        django_user = await sync_to_async(DjangoUser.objects.get)(username="tg_111222333")
        assert len(django_user.first_name) == 30

    async def test_add_user_without_username(self, storage, free_subscription):
        """username=None обрабатывается корректно"""
        await storage.add_user(
            user_id=444555666,
            username=None,
            full_name="No Username"
        )
        profile = await sync_to_async(TelegramProfile.objects.get)(telegram_id=444555666)
        assert profile.username == ""

    async def test_update_existing_user(self, storage, telegram_profile):
        """Обновление существующего пользователя"""
        original_id = telegram_profile.telegram_id
        await storage.add_user(
            user_id=original_id,
            username="updated_username",
            full_name="Updated Name"
        )
        profile = await sync_to_async(TelegramProfile.objects.get)(telegram_id=original_id)
        assert profile.username == "updated_username"
        assert profile.first_name == "Updated Name"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestDjangoStorageGetUser:
    """Тесты для DjangoStorage.get_user"""

    async def test_get_existing_user(self, storage, telegram_profile):
        """Получение существующего пользователя"""
        result = await storage.get_user(telegram_profile.telegram_id)
        assert result is not None
        assert result.telegram_id == telegram_profile.telegram_id

    async def test_get_nonexistent_user(self, storage):
        """Несуществующий пользователь возвращает None"""
        result = await storage.get_user(999999999)
        assert result is None


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestDjangoStorageAddUserState:
    """Тесты для DjangoStorage.add_user_state"""

    async def test_add_state_creates_state_type(self, storage, telegram_profile):
        """Создается новый StateType если не существует"""
        await storage.add_user_state(
            user_id=telegram_profile.telegram_id,
            state_name="new_state",
            description="New state description"
        )
        state_type = await sync_to_async(StateType.objects.get)(state_name="new_state")
        assert state_type.description == "New state description"
        user_state = await sync_to_async(UserState.objects.get)(
            telegram_profile=telegram_profile,
            state_type=state_type
        )
        assert user_state is not None

    async def test_add_state_reuses_existing_state_type(self, storage, telegram_profile, state_type):
        """Существующий StateType переиспользуется"""
        initial_count = await sync_to_async(StateType.objects.count)()
        await storage.add_user_state(
            user_id=telegram_profile.telegram_id,
            state_name=state_type.state_name,
            description="Different description"
        )
        final_count = await sync_to_async(StateType.objects.count)()
        assert final_count == initial_count

    async def test_add_state_for_nonexistent_user(self, storage):
        """Добавление состояния для несуществующего пользователя"""
        await storage.add_user_state(
            user_id=999999999,
            state_name="some_state"
        )
        count = await sync_to_async(UserState.objects.filter(state_type__state_name="some_state").count)()
        assert count == 0


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestDjangoStorageIsStaff:
    """Тесты для DjangoStorage.is_staff"""

    async def test_is_staff_true(self, storage, staff_user):
        """Staff пользователь возвращает True"""
        profile = await sync_to_async(TelegramProfile.objects.create)(
            user=staff_user,
            telegram_id=111222333,
            username="staff_profile"
        )
        result = await storage.is_staff(profile.telegram_id)
        assert result is True

    async def test_is_staff_false(self, storage, telegram_profile):
        """Обычный пользователь возвращает False"""
        telegram_profile.user.is_staff = False
        await sync_to_async(telegram_profile.user.save)()
        result = await storage.is_staff(telegram_profile.telegram_id)
        assert result is False

    async def test_is_staff_nonexistent_user(self, storage):
        """Несуществующий пользователь возвращает False"""
        result = await storage.is_staff(999999999)
        assert result is False


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestDjangoStorageGetStatistics:
    """Тесты для DjangoStorage.get_statistics"""

    async def test_statistics_empty_database(self, storage):
        """Статистика для пустой БД"""
        stats = await storage.get_statistics()
        assert stats["total_users"] == 0
        assert stats["recent_users"] == 0
        assert stats["completed_sessions"] == 0

    async def test_statistics_total_users(self, storage, free_subscription):
        """Подсчет total_users"""
        for i in range(3):
            await storage.add_user(
                user_id=100000 + i,
                username=f"user_{i}",
                full_name=f"User {i}"
            )
        stats = await storage.get_statistics()
        assert stats["total_users"] == 3

    async def test_statistics_completed_sessions(self, storage, telegram_profile):
        """Подсчет completed_sessions (distinct пользователи)"""
        work_finish = await sync_to_async(StateType.objects.create)(state_name="work_finish")
        await sync_to_async(UserState.objects.create)(
            telegram_profile=telegram_profile,
            state_type=work_finish
        )
        await sync_to_async(UserState.objects.create)(
            telegram_profile=telegram_profile,
            state_type=work_finish
        )
        stats = await storage.get_statistics()
        assert stats["completed_sessions"] == 1
