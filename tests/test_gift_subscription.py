from datetime import timedelta

import pytest
from django.contrib.auth.models import User as DjangoUser
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from bot.models import Subscription, TelegramProfile


@pytest.mark.django_db
class TestGiftSubscriptionModel:
    """Тесты метода TelegramProfile.gift_subscription"""

    @freeze_time("2026-05-28 12:00:00")
    def test_gift_to_free_user_activates_plan(self, telegram_profile, premium_subscription):
        """Юзеру на free дарим месяц — план меняется, expiry = now + duration."""
        assert telegram_profile.current_subscription.code == 'free'

        telegram_profile.gift_subscription(premium_subscription)
        telegram_profile.refresh_from_db()

        assert telegram_profile.current_subscription_id == premium_subscription.id
        expected = timezone.now() + timedelta(days=premium_subscription.duration_days)
        assert telegram_profile.subscription_expires_at == expected

    @freeze_time("2026-05-28 12:00:00")
    def test_gift_same_active_plan_extends(self, subscribed_profile, premium_subscription):
        """Если такой же тариф уже активен — срок продлевается."""
        original_expiry = subscribed_profile.subscription_expires_at
        assert original_expiry > timezone.now()

        subscribed_profile.gift_subscription(premium_subscription)
        subscribed_profile.refresh_from_db()

        expected = original_expiry + timedelta(days=premium_subscription.duration_days)
        assert subscribed_profile.subscription_expires_at == expected
        assert subscribed_profile.current_subscription_id == premium_subscription.id

    @freeze_time("2026-05-28 12:00:00")
    def test_gift_to_expired_user_starts_fresh(self, expired_profile, premium_subscription):
        """Истёкшему юзеру с тем же планом — срок считается от now, а не от старой даты."""
        # Фикстура строит дату от реального времени, а тест идёт в замороженном
        expired_profile.subscription_expires_at = timezone.now() - timedelta(days=1)
        expired_profile.save()

        expired_profile.gift_subscription(premium_subscription)
        expired_profile.refresh_from_db()

        expected = timezone.now() + timedelta(days=premium_subscription.duration_days)
        assert expired_profile.subscription_expires_at == expected

    @freeze_time("2026-05-28 12:00:00")
    def test_gift_different_plan_overrides(self, subscribed_profile):
        """Активный план monthly заменяется на другой план — срок = now + новый duration."""
        yearly = Subscription.objects.create(
            name='Годовая', code='yearly', price=3000,
            duration_days=365, daily_sessions_limit=5, is_active=True,
        )

        subscribed_profile.gift_subscription(yearly)
        subscribed_profile.refresh_from_db()

        assert subscribed_profile.current_subscription_id == yearly.id
        expected = timezone.now() + timedelta(days=365)
        assert subscribed_profile.subscription_expires_at == expected

    def test_gift_free_resets_expiry(self, subscribed_profile, free_subscription):
        """Подарок free-плана сбрасывает expiry (free всегда активен)."""
        subscribed_profile.gift_subscription(free_subscription)
        subscribed_profile.refresh_from_db()

        assert subscribed_profile.current_subscription_id == free_subscription.id
        assert subscribed_profile.subscription_expires_at is None


@pytest.mark.django_db
class TestGiftSubscriptionAdminAction:
    """Тесты admin-action 'Подарить подписку'"""

    @pytest.fixture
    def admin_client(self, client):
        admin_user = DjangoUser.objects.create_superuser(
            username='admin', email='a@a.a', password='pw'
        )
        client.force_login(admin_user)
        return client

    @pytest.fixture
    def captured_notifications(self, monkeypatch):
        """Перехватывает async_to_sync(_notify_telegram)(id, text) в admin."""
        calls = []

        def fake_async_to_sync(_callable):
            def caller(*args, **kwargs):
                calls.append({'args': args, 'kwargs': kwargs})
                return None
            return caller

        monkeypatch.setattr('bot.admin.async_to_sync', fake_async_to_sync)
        return calls

    def test_intermediate_form_renders(self, admin_client, telegram_profile, premium_subscription):
        """GET-выбор action рендерит промежуточную форму с тарифами."""
        url = reverse('admin:bot_telegramprofile_changelist')
        response = admin_client.post(url, {
            'action': 'gift_subscription_action',
            '_selected_action': [telegram_profile.pk],
        })
        assert response.status_code == 200
        assert b'subscription_plan' in response.content
        assert premium_subscription.name.encode() in response.content

    @freeze_time("2026-05-28 12:00:00")
    def test_apply_gifts_subscription(self, admin_client, telegram_profile, premium_subscription, captured_notifications):
        """POST с apply=Подарить активирует план и шлёт уведомление с датой окончания."""
        url = reverse('admin:bot_telegramprofile_changelist')
        response = admin_client.post(url, {
            'action': 'gift_subscription_action',
            '_selected_action': [telegram_profile.pk],
            'subscription_plan': premium_subscription.pk,
            'apply': 'Подарить',
        })
        assert response.status_code == 302

        telegram_profile.refresh_from_db()
        assert telegram_profile.current_subscription_id == premium_subscription.id
        expected = timezone.now() + timedelta(days=premium_subscription.duration_days)
        assert telegram_profile.subscription_expires_at == expected

        assert len(captured_notifications) == 1
        chat_id, text = captured_notifications[0]['args']
        assert chat_id == telegram_profile.telegram_id
        assert 'подарили' in text.lower()
        assert premium_subscription.name in text
        assert '27 июня 2026' in text  # 2026-05-28 + 30 дней

    def test_apply_without_plan_shows_error(self, admin_client, telegram_profile):
        """POST без выбранного плана не меняет подписку."""
        url = reverse('admin:bot_telegramprofile_changelist')
        original_sub_id = telegram_profile.current_subscription_id
        response = admin_client.post(url, {
            'action': 'gift_subscription_action',
            '_selected_action': [telegram_profile.pk],
            'subscription_plan': '',
            'apply': 'Подарить',
        }, follow=True)
        assert response.status_code == 200

        telegram_profile.refresh_from_db()
        assert telegram_profile.current_subscription_id == original_sub_id

    @freeze_time("2026-05-28 12:00:00")
    def test_apply_to_multiple_profiles(self, admin_client, telegram_profile, subscribed_profile, premium_subscription, captured_notifications):
        """Action работает с несколькими выбранными профилями и шлёт каждому уведомление."""
        url = reverse('admin:bot_telegramprofile_changelist')
        admin_client.post(url, {
            'action': 'gift_subscription_action',
            '_selected_action': [telegram_profile.pk, subscribed_profile.pk],
            'subscription_plan': premium_subscription.pk,
            'apply': 'Подарить',
        })

        telegram_profile.refresh_from_db()
        subscribed_profile.refresh_from_db()
        assert telegram_profile.current_subscription_id == premium_subscription.id
        assert subscribed_profile.current_subscription_id == premium_subscription.id

        assert len(captured_notifications) == 2
        notified_ids = {call['args'][0] for call in captured_notifications}
        assert notified_ids == {telegram_profile.telegram_id, subscribed_profile.telegram_id}
