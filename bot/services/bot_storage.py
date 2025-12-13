import logging
from datetime import datetime, timedelta
from typing import Optional
from asgiref.sync import sync_to_async
from django.contrib.auth.models import User as DjangoUser
from django.db.models import Count, Q
from django.utils import timezone

from bot.models import TelegramProfile, StateType, UserState


logger = logging.getLogger('mac_bot')


class DjangoStorage:
    """Класс для работы с БД через Django ORM вместо SQLAlchemy"""

    async def init_db(self):
        """Инициализация базы данных - для Django не требуется, миграции уже создали таблицы"""
        pass

    @sync_to_async
    def add_user(self, user_id: int, username: Optional[str], full_name: str) -> None:
        """Добавление или обновление пользователя Telegram"""
        try:
            # Создаем или получаем Django User
            django_user, created = DjangoUser.objects.get_or_create(
                username=f"tg_{user_id}",
                defaults={
                    'first_name': full_name[:30] if full_name else '',
                }
            )

            # Создаем или обновляем Telegram профиль
            profile, created = TelegramProfile.objects.update_or_create(
                telegram_id=user_id,
                defaults={
                    'user': django_user,
                    'username': username or '',
                    'first_name': full_name or '',
                }
            )

            if not created:
                # Обновляем last_request_time при повторном старте
                # Это поле добавим позже в модель
                logger.info(f"User updated: {username} (ID: {user_id})")
            else:
                logger.info(f"New user created: {username} (ID: {user_id})")

        except Exception as e:
            logger.error(f"Ошибка добавления пользователя: {e}")
            raise

    @sync_to_async
    def get_user(self, user_id: int) -> Optional[TelegramProfile]:
        """Получение пользователя Telegram по ID"""
        try:
            return TelegramProfile.objects.select_related('user').get(telegram_id=user_id)
        except TelegramProfile.DoesNotExist:
            return None
        except Exception as e:
            logger.error(f"Ошибка получения пользователя: {e}")
            raise

    @sync_to_async
    def add_user_state(
        self, user_id: int, state_name: str, description: Optional[str] = None
    ) -> None:
        """Добавление состояния пользователя"""
        try:
            # Получаем или создаем тип состояния
            state_type, created = StateType.objects.get_or_create(
                state_name=state_name,
                defaults={'description': description}
            )

            # Получаем профиль пользователя
            try:
                profile = TelegramProfile.objects.get(telegram_id=user_id)
            except TelegramProfile.DoesNotExist:
                logger.warning(f"User {user_id} not found for adding state")
                return

            # Создаем запись состояния пользователя
            UserState.objects.create(
                telegram_profile=profile,
                state_type=state_type
            )

        except Exception as e:
            logger.error(f"Ошибка добавления состояния пользователя: {e}")
            raise

    @sync_to_async
    def is_staff(self, user_id: int) -> bool:
        """Проверка, является ли пользователь staff"""
        try:
            profile = TelegramProfile.objects.select_related('user').get(telegram_id=user_id)
            return profile.user.is_staff
        except TelegramProfile.DoesNotExist:
            return False
        except Exception as e:
            logger.error(f"Ошибка проверки is_staff: {e}")
            return False

    @sync_to_async
    def get_statistics(self) -> dict:
        """Получение статистики по пользователям и состояниям"""
        try:
            # Общее количество пользователей
            total_users = TelegramProfile.objects.count()

            # Пользователи за последние 7 дней
            week_ago = timezone.now() - timedelta(days=7)
            recent_users = TelegramProfile.objects.filter(
                created_at__gte=week_ago
            ).count()

            # Завершенные сессии (пользователи, дошедшие до work_finish)
            completed_sessions = UserState.objects.filter(
                state_type__state_name__icontains='work_finish'
            ).values('telegram_profile').distinct().count()

            return {
                "total_users": total_users,
                "recent_users": recent_users,
                "completed_sessions": completed_sessions
            }

        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            raise
