from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class TelegramProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='telegram_profile'
    )
    telegram_id = models.BigIntegerField(unique=True)
    username = models.CharField(max_length=255, blank=True, null=True)
    first_name = models.CharField(max_length=255, blank=True)
    last_name = models.CharField(max_length=255, blank=True)
    language_code = models.CharField(max_length=10, default='ru')

    # Подписка
    subscription_active = models.BooleanField(default=False)
    subscription_expires_at = models.DateTimeField(null=True, blank=True)
    subscription_type = models.CharField(
        max_length=50,
        choices=[
            ('free', 'Бесплатная'),
            ('basic', 'Базовая'),
            ('premium', 'Премиум'),
        ],
        default='free'
    )

    # Метаданные
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_request_time = models.DateTimeField(null=True, blank=True)
    is_blocked = models.BooleanField(default=False)

    class Meta:
        db_table = 'telegram_profiles'
        verbose_name = 'Telegram профиль'
        verbose_name_plural = 'Telegram профили'

    def __str__(self):
        return f"{self.telegram_id} - {self.user.username}"

    @property
    def is_subscribed(self):
        """Активна ли подписка"""
        if not self.subscription_active:
            return False
        if self.subscription_expires_at:
            return self.subscription_expires_at > timezone.now()
        return True


class StateType(models.Model):
    id = models.AutoField(primary_key=True)
    state_name = models.CharField(max_length=50, unique=True)
    description = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "state_types"
        verbose_name = "State Type"
        verbose_name_plural = "State Types"

    def __str__(self):
        return self.state_name


class UserState(models.Model):
    id = models.AutoField(primary_key=True)
    telegram_profile = models.ForeignKey(
        TelegramProfile,
        on_delete=models.CASCADE,
        related_name="states"
    )
    state_type = models.ForeignKey(
        StateType,
        on_delete=models.PROTECT,
        related_name="user_states"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_states"
        verbose_name = "User State"
        verbose_name_plural = "User States"
        indexes = [
            models.Index(fields=["telegram_profile", "state_type"], name="ix_user_states_profile_type"),
            models.Index(fields=["created_at"], name="ix_user_states_created"),
        ]

    def __str__(self):
        return f"{self.telegram_profile.telegram_id} - {self.state_type.state_name}"
