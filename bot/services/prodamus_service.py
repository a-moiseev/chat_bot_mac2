import logging
import uuid
from typing import Dict, Optional

import aiohttp
from django.conf import settings
from prodamuspy import ProdamusPy

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
            secret_key = settings.PRODAMUS_SECRET_KEY + "demo"
            logger.info("[PRODAMUS] Using demo secret key (with 'demo' suffix)")
        else:
            secret_key = settings.PRODAMUS_SECRET_KEY

        # Создаем экземпляр ProdamusPy для подписания
        self.prodamus_py = ProdamusPy(secret=secret_key)

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
        signature = self.prodamus_py.sign(data)
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

        # Проверяем подпись через ProdamusPy
        is_valid = self.prodamus_py.verify(data_copy, received_signature)

        if not is_valid:
            logger.warning(
                f"Invalid webhook signature. Got: {received_signature[:10]}..."
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

    async def create_payment_link(
        self,
        order_id: str,
        subscription_plan: Subscription,
        user_id: int,
        username: Optional[str] = None,
    ) -> str:
        """Создание ссылки для оплаты через POST запрос к Prodamus API

        Args:
            order_id: Уникальный ID заказа
            subscription_plan: Объект тарифа из БД
            user_id: Telegram ID пользователя
            username: Telegram username (опционально)

        Returns:
            URL для оплаты через Prodamus
        """
        # Формируем параметры платежа
        payment_data = {
            "do": "link",  # Тип операции
            "order_id": order_id,
            "customer_extra": str(user_id),  # Сохраняем telegram_id для webhook
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
            # Преобразуем цену: если целое число, убираем .00
            price = subscription_plan.price
            price_str = str(int(price)) if price == int(price) else str(price)
            payment_data["products[0][price]"] = price_str
            payment_data["products[0][quantity]"] = "1"
            logger.warning(
                f"[PRODAMUS] No Prodamus subscription ID for plan {subscription_plan.code}, using products"
            )

        # Добавляем опциональные параметры
        if username:
            payment_data["customer_comment"] = f"Telegram: @{username}"

        # Тестовый режим
        if self.test_mode:
            payment_data["do"] = "test"
            logger.info("[PRODAMUS] Creating payment link in TEST mode")

        # Логируем параметры перед отправкой
        logger.info(f"[PRODAMUS API] Payment data before signing: {payment_data}")

        # Генерируем подпись
        signature = self.generate_signature(payment_data)
        payment_data["signature"] = signature

        logger.info(f"[PRODAMUS API] Generated signature: {signature[:20]}...")

        # Отправляем POST запрос к Prodamus
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.merchant_url,
                    data=payment_data,  # form-data формат
                    timeout=aiohttp.ClientTimeout(total=10),
                    allow_redirects=False,
                ) as response:
                    logger.info(f"[PRODAMUS API] Response status: {response.status}")
                    logger.info(
                        f"[PRODAMUS API] Response headers: {dict(response.headers)}"
                    )

                    # Вариант A: Prodamus возвращает 302 redirect
                    if response.status in [301, 302, 303, 307, 308]:
                        payment_url = response.headers.get('Location')
                        if not payment_url:
                            raise ValueError("No Location header in redirect response")

                        logger.info(
                            f"[PRODAMUS API] Got redirect URL: {payment_url}\n"
                            f"  Order: {order_id}\n"
                            f"  Product: {subscription_plan.name}\n"
                            f"  Price: {subscription_plan.price}₽\n"
                            f"  Subscription: YES (recurring)"
                        )

                        return payment_url

                    # Вариант B: Prodamus возвращает plain text URL в теле ответа
                    elif response.status == 200:
                        payment_url = await response.text()
                        payment_url = payment_url.strip()  # Убираем пробелы

                        logger.info(
                            f"[PRODAMUS API] Got payment URL: {payment_url}\n"
                            f"  Order: {order_id}\n"
                            f"  Product: {subscription_plan.name}\n"
                            f"  Price: {subscription_plan.price}₽\n"
                            f"  Subscription: YES (recurring)"
                        )

                        return payment_url

                    # Вариант C: Неожиданный статус
                    else:
                        text = await response.text()
                        logger.error(
                            f"[PRODAMUS API] Unexpected status code: {response.status}"
                        )
                        logger.error(f"[PRODAMUS API] Response body: {text[:500]}")
                        raise ValueError(f"Prodamus API error: {response.status}")

        except aiohttp.ClientError as e:
            logger.error(f"[PRODAMUS API] Request failed: {e}")
            raise ValueError(f"Failed to connect to Prodamus: {e}")

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
