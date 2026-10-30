from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth.models import User as DjangoUser
from django.utils import timezone

from bot.models import Payment, StateType, TelegramProfile, UserSession, UserState


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
        assert stats["days"] == 7
        assert stats["total_users"] == 0
        assert stats["current"] == {
            "new_users": 0,
            "active_users": 0,
            "started": 0,
            "completed": 0,
        }
        assert stats["previous"] == stats["current"]
        assert stats["stuck"] == {}
        assert stats["abandoned_payments"] == 0
        assert stats["total_sessions"] == 0
        assert stats["total_completed"] == 0

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

    async def test_statistics_all_time_counts_transitions(
        self, storage, telegram_profile
    ):
        """За всё время сессии считаются по work_1, завершения по work_finish"""
        work_1 = await sync_to_async(StateType.objects.create)(
            state_name="MacStates:work_1"
        )
        work_finish = await sync_to_async(StateType.objects.create)(
            state_name="MacStates:work_finish"
        )
        for state in (work_1, work_1, work_finish):
            await sync_to_async(UserState.objects.create)(
                telegram_profile=telegram_profile, state_type=state
            )
        stats = await storage.get_statistics()
        assert stats["total_sessions"] == 2
        assert stats["total_completed"] == 1

    async def test_statistics_period_and_previous(self, storage, telegram_profile):
        """Сессии делятся на текущий и предыдущий период"""
        now = timezone.now()
        await make_session(telegram_profile, now - timedelta(days=1), completed=True)
        await make_session(telegram_profile, now - timedelta(days=2))
        await make_session(telegram_profile, now - timedelta(days=10), completed=True)
        await make_session(telegram_profile, now - timedelta(days=20))

        stats = await storage.get_statistics(7)
        assert stats["current"]["started"] == 2
        assert stats["current"]["completed"] == 1
        assert stats["current"]["active_users"] == 1
        assert stats["current"]["new_users"] == 1
        assert stats["previous"]["started"] == 1
        assert stats["previous"]["completed"] == 1
        assert stats["previous"]["new_users"] == 0

    async def test_statistics_custom_days(self, storage, telegram_profile):
        """Период задается параметром"""
        await make_session(telegram_profile, timezone.now() - timedelta(days=20))
        stats = await storage.get_statistics(30)
        assert stats["days"] == 30
        assert stats["current"]["started"] == 1

    async def test_statistics_stuck_last_answered_step(
        self, storage, telegram_profile
    ):
        """Для незавершенной сессии берется последний отвеченный шаг"""
        started = timezone.now() - timedelta(days=1)
        await make_session(telegram_profile, started)
        await make_state(telegram_profile, "work_2", started + timedelta(minutes=1))
        await make_state(telegram_profile, "work_3", started + timedelta(minutes=2))

        stats = await storage.get_statistics()
        assert stats["stuck"] == {"work_3": 1}

    async def test_statistics_stuck_without_answers(self, storage, telegram_profile):
        """Без ответов после выдачи карты последним отвеченным считается work_1"""
        await make_session(telegram_profile, timezone.now() - timedelta(days=1))
        stats = await storage.get_statistics()
        assert stats["stuck"] == {"work_1": 1}

    async def test_statistics_stuck_bounded_by_next_session(
        self, storage, telegram_profile
    ):
        """Переходы следующей сессии не относятся к предыдущей"""
        first = timezone.now() - timedelta(days=2)
        second = timezone.now() - timedelta(days=1)
        await make_session(telegram_profile, first)
        await make_session(telegram_profile, second)
        await make_state(telegram_profile, "work_4", second + timedelta(minutes=1))

        stats = await storage.get_statistics()
        assert stats["stuck"] == {"work_1": 1, "work_4": 1}

    async def test_statistics_stuck_ignores_fresh_and_completed(
        self, storage, telegram_profile
    ):
        """Свежие и завершенные сессии не считаются брошенными"""
        await make_session(telegram_profile, timezone.now() - timedelta(minutes=10))
        await make_session(
            telegram_profile, timezone.now() - timedelta(days=1), completed=True
        )
        stats = await storage.get_statistics()
        assert stats["stuck"] == {}

    async def test_statistics_abandoned_payments(
        self, storage, telegram_profile, subscribed_profile, premium_subscription
    ):
        """Брошенная оплата - pending без успешной оплаты того же человека"""
        for order_id, profile, status in [
            ("a1", telegram_profile, "pending"),
            ("a2", telegram_profile, "pending"),
            ("b1", subscribed_profile, "pending"),
            ("b2", subscribed_profile, "success"),
        ]:
            await sync_to_async(Payment.objects.create)(
                telegram_profile=profile,
                subscription_plan=premium_subscription,
                order_id=order_id,
                amount=990,
                status=status,
            )
        stats = await storage.get_statistics()
        assert stats["abandoned_payments"] == 1


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestDjangoStorageGetRecentUsers:
    """Тесты для DjangoStorage.get_recent_users"""

    async def test_recent_users_empty(self, storage):
        data = await storage.get_recent_users()
        assert data == {"days": 7, "total": 0, "users": []}

    async def test_recent_users_new_profile_without_states(
        self, storage, telegram_profile
    ):
        """Только что зарегистрировавшийся пользователь попадает в список"""
        data = await storage.get_recent_users()
        assert data["total"] == 1
        user = data["users"][0]
        assert user["telegram_id"] == telegram_profile.telegram_id
        assert user["is_new"] is True
        assert user["is_paid"] is False
        assert user["started"] == 0
        assert user["last_state"] is None

    async def test_recent_users_excludes_inactive(self, storage, telegram_profile):
        """Пользователь без активности в периоде не показывается"""
        await sync_to_async(
            TelegramProfile.objects.filter(pk=telegram_profile.pk).update
        )(created_at=timezone.now() - timedelta(days=40))
        await make_state(telegram_profile, "work_2", timezone.now() - timedelta(days=20))
        data = await storage.get_recent_users(7)
        assert data["total"] == 0
        data = await storage.get_recent_users(30)
        assert data["total"] == 1
        assert data["users"][0]["is_new"] is False

    async def test_recent_users_sessions_and_last_state(
        self, storage, telegram_profile
    ):
        started = timezone.now() - timedelta(days=1)
        await make_session(telegram_profile, started, completed=True)
        await make_session(telegram_profile, timezone.now() - timedelta(days=20))
        await make_state(telegram_profile, "work_3", started + timedelta(minutes=1))

        user = (await storage.get_recent_users())["users"][0]
        assert user["started"] == 1
        assert user["completed"] == 1
        assert user["last_state"] == "work_3"

    async def test_recent_users_order_and_limit(
        self, storage, telegram_profile, subscribed_profile
    ):
        """Свежие первыми, лимит не влияет на total"""
        await make_state(
            subscribed_profile, "work_2", timezone.now() + timedelta(minutes=1)
        )
        data = await storage.get_recent_users(limit=1)
        assert data["total"] == 2
        assert len(data["users"]) == 1
        assert data["users"][0]["telegram_id"] == subscribed_profile.telegram_id
        assert data["users"][0]["is_paid"] is True


async def make_session(profile, started_at, completed=False):
    session = await sync_to_async(UserSession.objects.create)(
        telegram_profile=profile,
        request_text="request",
        request_type="коучинговый",
        card_type="день",
        card_number=1,
    )
    await sync_to_async(UserSession.objects.filter(pk=session.pk).update)(
        started_at=started_at,
        completed_at=started_at + timedelta(minutes=30) if completed else None,
    )


async def make_state(profile, name, created_at):
    state_type, _ = await sync_to_async(StateType.objects.get_or_create)(
        state_name=f"MacStates:{name}"
    )
    state = await sync_to_async(UserState.objects.create)(
        telegram_profile=profile, state_type=state_type
    )
    await sync_to_async(UserState.objects.filter(pk=state.pk).update)(
        created_at=created_at
    )
