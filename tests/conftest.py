import pytest
from django.contrib.auth.models import User as DjangoUser
from django.utils import timezone
from datetime import timedelta
from bot.models import TelegramProfile, StateType, UserState
from bot.services.bot_storage import DjangoStorage


@pytest.fixture
def storage():
    """Возвращает экземпляр DjangoStorage"""
    return DjangoStorage()


@pytest.fixture
def django_user(db):
    """Создает базового Django пользователя"""
    return DjangoUser.objects.create_user(
        username="test_user",
        first_name="Test",
        is_staff=False
    )


@pytest.fixture
def staff_user(db):
    """Создает staff пользователя"""
    return DjangoUser.objects.create_user(
        username="staff_user",
        first_name="Staff",
        is_staff=True
    )


@pytest.fixture
def telegram_profile(db, django_user):
    """Создает базовый TelegramProfile"""
    return TelegramProfile.objects.create(
        user=django_user,
        telegram_id=123456789,
        username="test_username",
        first_name="Test User"
    )


@pytest.fixture
def subscribed_profile(db):
    """Профиль с активной подпиской"""
    user = DjangoUser.objects.create_user(username="subscribed")
    future_date = timezone.now() + timedelta(days=30)
    return TelegramProfile.objects.create(
        user=user,
        telegram_id=987654321,
        username="subscribed_user",
        subscription_active=True,
        subscription_expires_at=future_date,
        subscription_type='premium'
    )


@pytest.fixture
def expired_profile(db):
    """Профиль с истекшей подпиской"""
    user = DjangoUser.objects.create_user(username="expired")
    past_date = timezone.now() - timedelta(days=1)
    return TelegramProfile.objects.create(
        user=user,
        telegram_id=111222333,
        username="expired_user",
        subscription_active=True,
        subscription_expires_at=past_date
    )


@pytest.fixture
def state_type(db):
    """Создает StateType"""
    return StateType.objects.create(
        state_name="test_state",
        description="Test state description"
    )
