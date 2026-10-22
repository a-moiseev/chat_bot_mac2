import logging

from asgiref.sync import async_to_sync
from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.shortcuts import render

from .models import TelegramProfile, StateType, UserState, Subscription, Payment, UserSession
from .views import _format_date_ru, _notify_telegram

logger = logging.getLogger("mac_bot")


@admin.register(TelegramProfile)
class TelegramProfileAdmin(admin.ModelAdmin):
    list_display = (
        'telegram_id',
        'username',
        'first_name',
        'last_name',
        'email',
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
    search_fields = ('telegram_id', 'username', 'first_name', 'last_name', 'user__username', 'email')
    readonly_fields = ('created_at', 'updated_at', 'is_subscribed')
    ordering = ('-created_at',)
    actions = ('gift_subscription_action',)

    fieldsets = (
        ('Telegram информация', {
            'fields': ('user', 'telegram_id', 'username', 'first_name', 'last_name', 'language_code', 'email')
        }),
        ('Подписка', {
            'fields': ('current_subscription', 'subscription_expires_at', 'is_subscribed')
        }),
        ('Статус', {
            'fields': ('is_blocked', 'created_at', 'updated_at')
        }),
    )

    @admin.action(description='Подарить подписку')
    def gift_subscription_action(self, request, queryset):
        if request.POST.get('apply'):
            plan_id = request.POST.get('subscription_plan')
            try:
                plan = Subscription.objects.get(pk=plan_id, is_active=True)
            except (Subscription.DoesNotExist, ValueError, TypeError):
                self.message_user(request, 'Выберите активный тариф', messages.ERROR)
                return None
            count = 0
            notified = 0
            for profile in queryset:
                profile.gift_subscription(plan)
                count += 1
                if not profile.subscription_expires_at:
                    continue
                expires_str = _format_date_ru(profile.subscription_expires_at)
                text = (
                    "🎁 <b>Вам подарили подписку!</b>\n\n"
                    f"Тариф: <b>{plan.name}</b>\n"
                    f"Действует до: <b>{expires_str}</b>\n\n"
                    "Нажмите /start чтобы начать сессию."
                )
                try:
                    async_to_sync(_notify_telegram)(profile.telegram_id, text)
                    notified += 1
                except Exception as e:
                    logger.warning(
                        f"[GIFT] Failed to notify {profile.telegram_id}: {e}"
                    )
            self.message_user(
                request,
                f'Подарено: {plan.name} ({plan.duration_days} дн.) — '
                f'пользователей: {count}, уведомлений отправлено: {notified}',
                messages.SUCCESS,
            )
            return HttpResponseRedirect(request.get_full_path())

        plans = (
            Subscription.objects
            .filter(is_active=True)
            .exclude(code='free')
            .order_by('price')
        )
        return render(
            request,
            'admin/bot/telegramprofile/gift_subscription.html',
            context={
                'profiles': queryset,
                'plans': plans,
                'action': 'gift_subscription_action',
                'title': 'Подарить подписку',
            },
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
    list_display = ('name', 'code', 'price', 'duration_days', 'daily_sessions_limit', 'cards_limit', 'prodamus_subscription_id', 'is_active')
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
        ('Интеграция Prodamus', {
            'fields': ('prodamus_subscription_id',)
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
