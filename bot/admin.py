from django.contrib import admin
from .models import TelegramProfile, StateType, UserState


@admin.register(TelegramProfile)
class TelegramProfileAdmin(admin.ModelAdmin):
    list_display = (
        'telegram_id',
        'username',
        'first_name',
        'last_name',
        'subscription_type',
        'is_subscribed',
        'is_blocked',
        'created_at'
    )
    list_filter = (
        'subscription_type',
        'subscription_active',
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
            'fields': ('subscription_type', 'subscription_active', 'subscription_expires_at')
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
