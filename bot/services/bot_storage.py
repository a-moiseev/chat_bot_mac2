import logging
from datetime import datetime, timedelta
from typing import Optional
from asgiref.sync import sync_to_async
from django.contrib.auth.models import User as DjangoUser
from django.db.models import Count, Q
from django.utils import timezone

from bot.models import TelegramProfile, StateType, UserState, Payment, Subscription, UserSession


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

            # Если нет подписки, назначаем free
            if not profile.current_subscription:
                free_subscription = Subscription.objects.get(code='free')
                profile.current_subscription = free_subscription
                profile.save()
                logger.info(f"Assigned free subscription to user {user_id}")

            if not created:
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

    @sync_to_async
    def create_payment_order(
        self, user_id: int, plan_code: str, username: Optional[str] = None
    ) -> tuple[str, str]:
        """Создание заказа на оплату подписки

        Returns:
            tuple[order_id, payment_url]: ID заказа и ссылка на оплату
        """
        try:
            logger.info(f"[PAYMENT] Starting create_payment_order for user {user_id}, plan {plan_code}")
            from bot.services.prodamus_service import ProdamusService

            # Получаем тариф из БД
            try:
                logger.info(f"[PAYMENT] Looking for subscription plan: {plan_code}")
                subscription_plan = Subscription.objects.get(code=plan_code, is_active=True)
                logger.info(f"[PAYMENT] Found subscription: {subscription_plan.name}, price: {subscription_plan.price}")
            except Subscription.DoesNotExist:
                logger.error(f"[PAYMENT] Subscription plan '{plan_code}' not found or inactive")
                raise ValueError(f"Тариф '{plan_code}' не найден")

            # Получаем профиль пользователя
            try:
                logger.info(f"[PAYMENT] Looking for user profile: {user_id}")
                profile = TelegramProfile.objects.get(telegram_id=user_id)
                logger.info(f"[PAYMENT] Found profile: {profile}")
            except TelegramProfile.DoesNotExist:
                logger.error(f"[PAYMENT] User {user_id} not found")
                raise ValueError(f"Пользователь не найден")

            # Создаем сервис Prodamus
            logger.info(f"[PAYMENT] Creating Prodamus service")
            prodamus = ProdamusService()

            # Генерируем order_id
            logger.info(f"[PAYMENT] Generating order_id")
            order_id = prodamus.generate_order_id(user_id, plan_code)
            logger.info(f"[PAYMENT] Generated order_id: {order_id}")

            # Создаем Payment запись
            logger.info(f"[PAYMENT] Creating Payment record in DB")
            payment = Payment.objects.create(
                telegram_profile=profile,
                subscription_plan=subscription_plan,
                order_id=order_id,
                amount=subscription_plan.price,
                status='pending'
            )
            logger.info(f"[PAYMENT] Payment record created: {payment}")

            # Генерируем платежную ссылку
            logger.info(f"[PAYMENT] Generating payment URL")
            payment_url = prodamus.create_payment_link(
                order_id=order_id,
                subscription_plan=subscription_plan,
                user_id=user_id,
                username=username
            )
            logger.info(f"[PAYMENT] Payment URL generated: {payment_url[:100]}...")

            logger.info(
                f"[PAYMENT] SUCCESS: Created payment order {order_id} for user {user_id}: "
                f"{subscription_plan.name} ({subscription_plan.price}₽)"
            )

            return order_id, payment_url

        except Exception as e:
            logger.error(f"[PAYMENT] ERROR creating payment order: {e}", exc_info=True)
            raise

    @sync_to_async
    def can_start_session(self, user_id: int) -> bool:
        """Проверка возможности начать новую сессию"""
        try:
            profile = TelegramProfile.objects.select_related('current_subscription').get(
                telegram_id=user_id
            )
            return profile.can_start_session()
        except TelegramProfile.DoesNotExist:
            logger.warning(f"User {user_id} not found for session check")
            return False
        except Exception as e:
            logger.error(f"Error checking session limit: {e}")
            return False

    @sync_to_async
    def create_session(
        self,
        user_id: int,
        request_text: str,
        request_type: str,
        card_type: str,
        card_number: int
    ) -> None:
        """Создание новой сессии пользователя"""
        try:
            profile = TelegramProfile.objects.get(telegram_id=user_id)

            UserSession.objects.create(
                telegram_profile=profile,
                request_text=request_text,
                request_type=request_type,
                card_type=card_type,
                card_number=card_number,
                started_at=timezone.now()
            )

            logger.info(
                f"Created session for user {user_id}: {request_type}, "
                f"card {card_type} #{card_number}"
            )

        except TelegramProfile.DoesNotExist:
            logger.error(f"User {user_id} not found for creating session")
        except Exception as e:
            logger.error(f"Error creating session: {e}")
            raise

    @sync_to_async
    def complete_latest_session(self, user_id: int) -> None:
        """Завершение последней незавершенной сессии пользователя"""
        try:
            profile = TelegramProfile.objects.get(telegram_id=user_id)

            # Находим последнюю незавершенную сессию
            session = UserSession.objects.filter(
                telegram_profile=profile,
                completed_at__isnull=True
            ).order_by('-started_at').first()

            if session:
                session.completed_at = timezone.now()
                session.save()
                logger.info(f"Completed session {session.id} for user {user_id}")
            else:
                logger.warning(f"No active session found for user {user_id}")

        except TelegramProfile.DoesNotExist:
            logger.error(f"User {user_id} not found for completing session")
        except Exception as e:
            logger.error(f"Error completing session: {e}")
            raise

    @sync_to_async
    def get_user_cards_limit(self, user_id: int) -> Optional[int]:
        """Получение лимита доступных карт для пользователя

        Returns:
            int: лимит для free (10)
            None: без ограничений для premium
        """
        profile = TelegramProfile.objects.select_related('current_subscription').get(
            telegram_id=user_id
        )
        return profile.get_available_card_count()
