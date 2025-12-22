from django.contrib import admin
from .models import TelegramProfile, StateType, UserState, Subscription, Payment, UserSession


@admin.register(TelegramProfile)
class TelegramProfileAdmin(admin.ModelAdmin):
    list_display = (
        'telegram_id',
        'username',
        'first_name',
        'last_name',
        'current_subscription',
        'is_subscribed',
        'is_blocked',
        'created_at'
    )
    list_filter = (
        'current_subscription',
        'is_blocked',
        'created_at',
        'language_code'
    )
    search_fields = ('telegram_id', 'username', 'first_name', 'last_name', 'user__username')
    readonly_fields = ('created_at', 'updated_at', 'is_subscribed')
    ordering = ('-created_at',)

    fieldsets = (
        ('Telegram информация', {
            'fields': ('user', 'telegram_id', 'username', 'first_name', 'last_name', 'language_code')
        }),
        ('Подписка', {
            'fields': ('current_subscription', 'subscription_expires_at', 'is_subscribed')
        }),
        ('Статус', {
            'fields': ('is_blocked', 'created_at', 'updated_at')
        }),
    )


@admin.register(StateType)
class StateTypeAdmin(admin.ModelAdmin):
    list_display = ('id', 'state_name', 'description', 'created_at')
    search_fields = ('state_name', 'description')
    list_filter = ('created_at',)
    ordering = ('state_name',)


@admin.register(UserState)
class UserStateAdmin(admin.ModelAdmin):
    list_display = ('id', 'telegram_profile', 'state_type', 'created_at')
    list_filter = ('state_type', 'created_at')
    search_fields = (
        'telegram_profile__telegram_id',
        'telegram_profile__username',
        'state_type__state_name'
    )
    ordering = ('-created_at',)
    raw_id_fields = ('telegram_profile',)
    autocomplete_fields = ('state_type',)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'price', 'duration_days', 'daily_sessions_limit', 'cards_limit', 'is_active')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'code', 'description')
    ordering = ('price',)
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('Основная информация', {
            'fields': ('name', 'code', 'description', 'is_active')
        }),
        ('Цена и длительность', {
            'fields': ('price', 'duration_days')
        }),
        ('Лимиты', {
            'fields': ('daily_sessions_limit', 'cards_limit')
        }),
        ('Метаданные', {
            'fields': ('created_at', 'updated_at')
        }),
    )


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('order_id', 'telegram_profile', 'subscription_plan', 'amount', 'status', 'created_at', 'paid_at')
    list_filter = ('status', 'subscription_plan', 'created_at')
    search_fields = (
        'order_id',
        'payment_id',
        'telegram_profile__telegram_id',
        'telegram_profile__username',
        'customer_email'
    )
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at', 'webhook_data')
    raw_id_fields = ('telegram_profile',)

    fieldsets = (
        ('Основная информация', {
            'fields': ('telegram_profile', 'subscription_plan', 'status')
        }),
        ('Данные Prodamus', {
            'fields': ('order_id', 'payment_id', 'subscription_id')
        }),
        ('Детали платежа', {
            'fields': ('amount', 'currency', 'paid_at')
        }),
        ('Данные клиента', {
            'fields': ('customer_email', 'customer_phone')
        }),
        ('Отладка', {
            'fields': ('webhook_data', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'telegram_profile', 'request_type', 'card_type', 'card_number', 'started_at', 'completed_at')
    list_filter = ('request_type', 'card_type', 'started_at')
    search_fields = (
        'telegram_profile__telegram_id',
        'telegram_profile__username',
        'request_text'
    )
    ordering = ('-started_at',)
    readonly_fields = ('started_at',)
    raw_id_fields = ('telegram_profile',)

    fieldsets = (
        ('Пользователь', {
            'fields': ('telegram_profile',)
        }),
        ('Детали сессии', {
            'fields': ('request_text', 'request_type', 'card_type', 'card_number')
        }),
        ('Временные метки', {
            'fields': ('started_at', 'completed_at')
        }),
    )
