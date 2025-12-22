from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta


class Subscription(models.Model):
    """Тарифные планы подписки"""

    name = models.CharField(max_length=100, verbose_name='Название тарифа')
    code = models.CharField(max_length=50, unique=True, verbose_name='Код тарифа')
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Цена (₽)')
    duration_days = models.IntegerField(verbose_name='Продолжительность (дни)')
    daily_sessions_limit = models.IntegerField(verbose_name='Лимит сессий в день')
    cards_limit = models.IntegerField(verbose_name='Количество доступных карт', null=True, blank=True)
    is_active = models.BooleanField(default=True, verbose_name='Активен')
    description = models.TextField(blank=True, verbose_name='Описание')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'subscriptions'
        verbose_name = 'Тариф подписки'
        verbose_name_plural = 'Тарифы подписок'
        ordering = ['price']

    def __str__(self):
        return f"{self.name} ({self.price}₽)"


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
    current_subscription = models.ForeignKey(
        Subscription,
        on_delete=models.PROTECT,
        related_name='users',
        null=True,
        blank=True,
        verbose_name='Текущая подписка'
    )
    subscription_expires_at = models.DateTimeField(null=True, blank=True, verbose_name='Подписка до')

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
        if not self.current_subscription:
            return False
        # Free тариф всегда активен
        if self.current_subscription.code == 'free':
            return True
        # Платные тарифы - проверяем дату истечения
        if self.subscription_expires_at:
            return self.subscription_expires_at > timezone.now()
        return False

    def get_daily_sessions_count(self):
        """Получить количество сессий начатых сегодня"""
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return self.sessions.filter(started_at__gte=today_start).count()

    def get_daily_session_limit(self):
        """Получить лимит сессий в день на основе подписки"""
        if self.current_subscription:
            return self.current_subscription.daily_sessions_limit
        return 1  # Fallback для пользователей без подписки

    def can_start_session(self):
        """Проверить, может ли пользователь начать новую сессию сегодня"""
        return self.get_daily_sessions_count() < self.get_daily_session_limit()

    def get_available_card_count(self):
        """Получить количество доступных карт для одной колоды"""
        return self.current_subscription.cards_limit

    def activate_subscription(self, subscription_plan):
        """Активировать подписку на указанный план"""
        self.current_subscription = subscription_plan
        # Для free тарифа дата истечения не нужна
        if subscription_plan.code != 'free':
            self.subscription_expires_at = timezone.now() + timedelta(days=subscription_plan.duration_days)
        else:
            self.subscription_expires_at = None
        self.save()


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


class Payment(models.Model):
    """Платежные транзакции Prodamus"""

    PAYMENT_STATUS = [
        ('pending', 'Ожидает оплаты'),
        ('success', 'Успешно оплачено'),
        ('failed', 'Ошибка оплаты'),
        ('cancelled', 'Отменено'),
        ('refunded', 'Возвращено'),
    ]

    telegram_profile = models.ForeignKey(
        TelegramProfile,
        on_delete=models.CASCADE,
        related_name='payments',
        verbose_name='Telegram профиль'
    )
    subscription_plan = models.ForeignKey(
        Subscription,
        on_delete=models.PROTECT,
        related_name='payments',
        verbose_name='Тарифный план',
        null=True,
        blank=True
    )

    # Данные Prodamus
    order_id = models.CharField(max_length=255, unique=True, verbose_name='ID заказа')
    payment_id = models.CharField(max_length=255, blank=True, null=True, verbose_name='ID платежа')
    subscription_id = models.CharField(max_length=255, blank=True, null=True, verbose_name='ID подписки Prodamus')

    # Детали платежа
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Сумма')
    currency = models.CharField(max_length=3, default='RUB', verbose_name='Валюта')
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default='pending', verbose_name='Статус')

    # Данные клиента
    customer_email = models.EmailField(blank=True, null=True, verbose_name='Email клиента')
    customer_phone = models.CharField(max_length=50, blank=True, null=True, verbose_name='Телефон клиента')

    # Метаданные
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Создано')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Обновлено')
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name='Оплачено')

    # Сырые данные webhook для отладки
    webhook_data = models.JSONField(null=True, blank=True, verbose_name='Данные webhook')

    class Meta:
        db_table = 'payments'
        verbose_name = 'Платеж'
        verbose_name_plural = 'Платежи'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['order_id'], name='ix_payments_order_id'),
            models.Index(fields=['telegram_profile', 'status'], name='ix_payments_profile_status'),
        ]

    def __str__(self):
        return f"{self.order_id} - {self.status} ({self.amount}₽)"


class UserSession(models.Model):
    """Сессии пользователей для отслеживания дневных лимитов"""

    telegram_profile = models.ForeignKey(
        TelegramProfile,
        on_delete=models.CASCADE,
        related_name='sessions',
        verbose_name='Telegram профиль'
    )

    # Временные метки
    started_at = models.DateTimeField(auto_now_add=True, verbose_name='Начало сессии')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='Завершение сессии')

    # Детали сессии
    request_text = models.TextField(verbose_name='Текст запроса')
    request_type = models.CharField(max_length=50, verbose_name='Тип запроса')
    card_type = models.CharField(max_length=20, verbose_name='Тип карты')
    card_number = models.IntegerField(verbose_name='Номер карты')

    class Meta:
        db_table = 'user_sessions'
        verbose_name = 'Сессия пользователя'
        verbose_name_plural = 'Сессии пользователей'
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['telegram_profile', 'started_at'], name='ix_sessions_profile_start'),
            models.Index(fields=['started_at'], name='ix_sessions_started'),
        ]

    def __str__(self):
        return f"{self.telegram_profile.telegram_id} - {self.started_at.strftime('%Y-%m-%d %H:%M')}"
