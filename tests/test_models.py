import pytest
from django.contrib.auth.models import User as DjangoUser
from django.utils import timezone
from freezegun import freeze_time

from bot.models import StateType, TelegramProfile, UserState


@pytest.mark.django_db
class TestTelegramProfile:
    """Тесты для модели TelegramProfile"""

    def test_create_profile(self, django_user):
        """Базовое создание профиля"""
        profile = TelegramProfile.objects.create(
            user=django_user,
            telegram_id=123456789,
            username="test_user",
            first_name="Test"
        )
        assert profile.telegram_id == 123456789
        assert profile.username == "test_user"

    def test_telegram_id_unique(self, django_user):
        """telegram_id должен быть уникальным"""
        TelegramProfile.objects.create(
            user=django_user,
            telegram_id=123456789,
            username="user1"
        )
        other_user = DjangoUser.objects.create_user(username="other")
        with pytest.raises(Exception):
            TelegramProfile.objects.create(
                user=other_user,
                telegram_id=123456789,
                username="user2"
            )

    def test_is_subscribed_free(self, telegram_profile):
        """is_subscribed = True для бесплатного тарифа"""
        # telegram_profile уже имеет free подписку из фикстуры
        assert telegram_profile.current_subscription.code == 'free'
        assert telegram_profile.is_subscribed is True

    def test_is_subscribed_no_subscription(self, django_user):
        """is_subscribed = False если нет подписки"""
        profile = TelegramProfile.objects.create(
            user=django_user,
            telegram_id=999888777,
            current_subscription=None
        )
        assert profile.is_subscribed is False

    def test_is_subscribed_active_future(self, subscribed_profile):
        """is_subscribed = True если премиум и дата в будущем"""
        assert subscribed_profile.current_subscription.code == 'monthly'
        assert subscribed_profile.subscription_expires_at > timezone.now()
        assert subscribed_profile.is_subscribed is True

    def test_is_subscribed_expired(self, expired_profile):
        """is_subscribed = False если премиум подписка истекла"""
        assert expired_profile.current_subscription.code == 'monthly'
        assert expired_profile.subscription_expires_at < timezone.now()
        assert expired_profile.is_subscribed is False

    @freeze_time("2025-01-15 12:00:00")
    def test_is_subscribed_exact_moment(self, django_user, premium_subscription):
        """Проверка граничного случая - точный момент истечения"""
        exact_time = timezone.now()
        profile = TelegramProfile.objects.create(
            user=django_user,
            telegram_id=555666777,
            current_subscription=premium_subscription,
            subscription_expires_at=exact_time
        )
        assert profile.is_subscribed is False

    def test_str_method(self, telegram_profile):
        """Проверка __str__"""
        expected = f"{telegram_profile.telegram_id} - {telegram_profile.user.username}"
        assert str(telegram_profile) == expected


@pytest.mark.django_db
class TestStateType:
    """Тесты для модели StateType"""

    def test_create_state_type(self):
        """Базовое создание StateType"""
        state = StateType.objects.create(
            state_name="work_1",
            description="First work state"
        )
        assert state.state_name == "work_1"
        assert state.description == "First work state"

    def test_state_name_unique(self):
        """state_name должен быть уникальным"""
        StateType.objects.create(state_name="work_1")
        with pytest.raises(Exception):
            StateType.objects.create(state_name="work_1")

    def test_description_nullable(self):
        """description может быть null"""
        state = StateType.objects.create(state_name="work_2", description=None)
        assert state.description is None

    def test_str_method(self):
        """Проверка __str__"""
        state = StateType.objects.create(state_name="work_finish")
        assert str(state) == "work_finish"


@pytest.mark.django_db
class TestUserState:
    """Тесты для модели UserState"""

    def test_create_user_state(self, telegram_profile, state_type):
        """Базовое создание UserState"""
        user_state = UserState.objects.create(
            telegram_profile=telegram_profile,
            state_type=state_type
        )
        assert user_state.telegram_profile == telegram_profile
        assert user_state.state_type == state_type
        assert user_state.created_at is not None

    def test_foreign_key_relationships(self, telegram_profile, state_type):
        """Проверка связей ForeignKey"""
        user_state = UserState.objects.create(
            telegram_profile=telegram_profile,
            state_type=state_type
        )
        assert user_state in telegram_profile.states.all()
        assert user_state in state_type.user_states.all()

    def test_cascade_delete_profile(self, telegram_profile, state_type):
        """Удаление profile удаляет user_states (CASCADE)"""
        UserState.objects.create(
            telegram_profile=telegram_profile,
            state_type=state_type
        )
        profile_id = telegram_profile.id
        telegram_profile.delete()
        assert UserState.objects.filter(telegram_profile_id=profile_id).count() == 0

    def test_protect_delete_state_type(self, telegram_profile, state_type):
        """Удаление StateType с user_states вызывает ошибку (PROTECT)"""
        UserState.objects.create(
            telegram_profile=telegram_profile,
            state_type=state_type
        )
        with pytest.raises(Exception):
            state_type.delete()

    def test_multiple_states_per_user(self, telegram_profile):
        """Один пользователь может иметь несколько состояний"""
        state1 = StateType.objects.create(state_name="work_1")
        state2 = StateType.objects.create(state_name="work_2")
        UserState.objects.create(telegram_profile=telegram_profile, state_type=state1)
        UserState.objects.create(telegram_profile=telegram_profile, state_type=state2)
        assert telegram_profile.states.count() == 2

    def test_str_method(self, telegram_profile, state_type):
        """Проверка __str__"""
        user_state = UserState.objects.create(
            telegram_profile=telegram_profile,
            state_type=state_type
        )
        expected = f"{telegram_profile.telegram_id} - {state_type.state_name}"
        assert str(user_state) == expected
