from datetime import timedelta

import pytest
from django.contrib.auth.models import User as DjangoUser
from django.utils import timezone

from bot.models import StateType, TelegramProfile, Subscription
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
def free_subscription(db):
    """Создает бесплатный тариф"""
    return Subscription.objects.create(
        name='Бесплатный',
        code='free',
        price=0,
        duration_days=999999,
        daily_sessions_limit=1,
        cards_limit=10,
        is_active=True
    )


@pytest.fixture
def premium_subscription(db):
    """Создает премиум тариф"""
    return Subscription.objects.create(
        name='Премиум',
        code='monthly',
        price=300,
        duration_days=30,
        daily_sessions_limit=3,
        cards_limit=None,
        is_active=True
    )


@pytest.fixture
def telegram_profile(db, django_user, free_subscription):
    """Создает базовый TelegramProfile с бесплатной подпиской"""
    return TelegramProfile.objects.create(
        user=django_user,
        telegram_id=123456789,
        username="test_username",
        first_name="Test User",
        current_subscription=free_subscription
    )


@pytest.fixture
def subscribed_profile(db, premium_subscription):
    """Профиль с активной премиум подпиской"""
    user = DjangoUser.objects.create_user(username="subscribed")
    future_date = timezone.now() + timedelta(days=30)
    return TelegramProfile.objects.create(
        user=user,
        telegram_id=987654321,
        username="subscribed_user",
        current_subscription=premium_subscription,
        subscription_expires_at=future_date
    )


@pytest.fixture
def expired_profile(db, premium_subscription):
    """Профиль с истекшей премиум подпиской"""
    user = DjangoUser.objects.create_user(username="expired")
    past_date = timezone.now() - timedelta(days=1)
    return TelegramProfile.objects.create(
        user=user,
        telegram_id=111222333,
        username="expired_user",
        current_subscription=premium_subscription,
        subscription_expires_at=past_date
    )


@pytest.fixture
def state_type(db):
    """Создает StateType"""
    return StateType.objects.create(
        state_name="test_state",
        description="Test state description"
    )
