import hashlib
import hmac
import json
import logging
import uuid
from typing import Dict, Optional
from urllib.parse import urlencode

from django.conf import settings

from bot.models import Subscription

logger = logging.getLogger("mac_bot")


class ProdamusService:
    """Сервис для интеграции с платежной системой Prodamus

    Документация API: https://docs.prodamuspay.ru/en/
    """

    def __init__(self):
        """Инициализация сервиса с настройками из Django settings"""
        self.merchant_url = settings.PRODAMUS_MERCHANT_URL
        self.test_mode = settings.PRODAMUS_TEST_MODE

        # Для демо-платежей добавляем суффикс "demo" к ключу
        if self.test_mode:
            self.secret_key = settings.PRODAMUS_SECRET_KEY + "demo"
            logger.info("[PRODAMUS] Using demo secret key (with 'demo' suffix)")
        else:
            self.secret_key = settings.PRODAMUS_SECRET_KEY

    def generate_order_id(self, user_id: int, plan_code: str) -> str:
        """Генерация уникального ID заказа

        Args:
            user_id: Telegram ID пользователя
            plan_code: Код тарифа (free/monthly/yearly)

        Returns:
            Уникальный order_id формата: ORDER_{user_id}_{plan}_{uuid}
        """
        unique_id = uuid.uuid4().hex[:8]
        order_id = f"ORDER_{user_id}_{plan_code}_{unique_id}"
        logger.info(f"Generated order_id: {order_id}")
        return order_id

    def generate_signature(self, data: Dict[str, str]) -> str:
        """Генерация HMAC SHA256 подписи для запроса к Prodamus

        Args:
            data: Словарь с параметрами платежа

        Returns:
            HMAC SHA256 подпись в hex формате
        """
        # Сортируем параметры по ключам (alphabetically)
        sorted_data = dict(sorted(data.items()))

        # Формат Prodamus: преобразуем в JSON строку
        # Используем separators для компактного формата без пробелов
        json_string = json.dumps(sorted_data, ensure_ascii=False, separators=(',', ':'))

        logger.info(
            f"[SIGNATURE] JSON to sign (first 200 chars): {json_string[:200]}"
        )
        logger.info(f"[SIGNATURE] Secret key length: {len(self.secret_key)} chars")
        logger.info(f"[SIGNATURE] Secret key first 10 chars: {self.secret_key[:10]}...")

        # Генерируем HMAC SHA256 от JSON строки
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            json_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        logger.info(f"[SIGNATURE] Generated signature: {signature}")
        return signature

    def verify_webhook_signature(self, data: Dict, received_signature: str) -> bool:
        """Проверка подписи webhook от Prodamus

        Args:
            data: Данные webhook от Prodamus
            received_signature: Подпись, полученная от Prodamus

        Returns:
            True если подпись валидна, False иначе
        """
        # Убираем signature из данных перед проверкой
        data_copy = {k: v for k, v in data.items() if k != "signature"}

        # Генерируем ожидаемую подпись
        expected_signature = self.generate_signature(data_copy)

        # Сравниваем в безопасном режиме (защита от timing attacks)
        is_valid = hmac.compare_digest(expected_signature, received_signature)

        if not is_valid:
            logger.warning(
                f"Invalid webhook signature. Expected: {expected_signature[:10]}..., Got: {received_signature[:10]}..."
            )

        return is_valid

    def get_subscription_by_code(self, plan_code: str) -> Optional[Subscription]:
        """Получение тарифа из БД по коду

        Args:
            plan_code: Код тарифа (free/monthly/yearly)

        Returns:
            Объект Subscription или None если не найден
        """
        try:
            subscription = Subscription.objects.get(code=plan_code, is_active=True)
            logger.debug(
                f"Found subscription: {subscription.name} ({subscription.code})"
            )
            return subscription
        except Subscription.DoesNotExist:
            logger.error(f"Subscription with code '{plan_code}' not found or inactive")
            return None

    def create_payment_link(
        self,
        order_id: str,
        subscription_plan: Subscription,
        user_id: int,
        username: Optional[str] = None,
        email: Optional[str] = None,
    ) -> str:
        """Создание ссылки для оплаты через Prodamus

        Args:
            order_id: Уникальный ID заказа
            subscription_plan: Объект тарифа из БД
            user_id: Telegram ID пользователя
            username: Telegram username (опционально)
            email: Email пользователя (опционально)

        Returns:
            URL для оплаты через Prodamus
        """
        # Формируем параметры платежа
        payment_data = {
            "do": "link",  # Тип операции
            "order_id": order_id,
            "customer_extra": str(user_id),  # Сохраняем telegram_id для webhook
            "urlNotification": settings.PRODAMUS_WEBHOOK_URL,
            "urlSuccess": settings.PRODAMUS_SUCCESS_URL,
            "sys": "mac_bot",  # Идентификатор системы
        }

        # Добавляем ID подписки Prodamus для рекуррентных платежей
        if subscription_plan.prodamus_subscription_id:
            # Для подписки НЕ добавляем products, только subscription ID
            payment_data["subscription"] = str(
                subscription_plan.prodamus_subscription_id
            )
            logger.info(
                f"[PRODAMUS] Using Prodamus subscription ID: {subscription_plan.prodamus_subscription_id}"
            )
        else:
            # Для разовой оплаты (если нет subscription_id) добавляем products
            payment_data["products[0][name]"] = subscription_plan.name
            payment_data["products[0][price]"] = str(subscription_plan.price)
            payment_data["products[0][quantity]"] = "1"
            logger.warning(
                f"[PRODAMUS] No Prodamus subscription ID for plan {subscription_plan.code}, using products"
            )

        # Добавляем urlReturn только если он не пустой
        if settings.PRODAMUS_RETURN_URL:
            payment_data["urlReturn"] = settings.PRODAMUS_RETURN_URL

        # Добавляем опциональные параметры
        if username:
            payment_data["customer_comment"] = f"Telegram: @{username}"

        if email:
            payment_data["customer_email"] = email

        # Тестовый режим
        if self.test_mode:
            payment_data["do"] = "test"
            logger.info("[PRODAMUS] Creating payment link in TEST mode")

        # Логируем параметры перед отправкой
        logger.info(f"[PRODAMUS] Payment data before signing: {payment_data}")

        # Генерируем подпись
        signature = self.generate_signature(payment_data)
        payment_data["signature"] = signature

        logger.info(f"[PRODAMUS] Generated signature: {signature[:20]}...")

        # Формируем URL
        query_string = urlencode(payment_data)
        payment_url = f"{self.merchant_url}?{query_string}"

        logger.info(
            f"[PRODAMUS] Sending request to Prodamus:\n"
            f"  URL: {self.merchant_url}\n"
            f"  Order: {order_id}\n"
            f"  Product: {subscription_plan.name}\n"
            f"  Price: {subscription_plan.price}₽\n"
            f"  Subscription: YES (recurring)\n"
            f"  Full URL length: {len(payment_url)} chars"
        )

        return payment_url

    def get_plan_info(self, plan_code: str) -> Optional[Dict]:
        """Получить информацию о тарифе

        Args:
            plan_code: Код тарифа

        Returns:
            Словарь с информацией о тарифе или None
        """
        subscription = self.get_subscription_by_code(plan_code)
        if not subscription:
            return None

        return {
            "name": subscription.name,
            "code": subscription.code,
            "price": float(subscription.price),
            "duration_days": subscription.duration_days,
            "daily_sessions_limit": subscription.daily_sessions_limit,
            "cards_limit": subscription.cards_limit,
        }
