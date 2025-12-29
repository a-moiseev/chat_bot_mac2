import logging

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from bot.models import Payment, TelegramProfile
from bot.services.prodamus_service import ProdamusService

logger = logging.getLogger("mac_bot")


@csrf_exempt
@require_POST
def prodamus_webhook(request):
    """Обработка webhook уведомлений от Prodamus

    Prodamus отправляет POST запрос с данными о платеже:
    - order_id: уникальный ID заказа
    - payment_status: статус платежа (success/failed/cancelled)
    - payment_id: ID платежа в системе Prodamus
    - customer_extra: telegram_id пользователя
    - signature: HMAC SHA256 подпись для проверки
    """
    try:
        # Парсим данные из POST запроса
        data = request.POST.dict()

        # Детальное логирование webhook
        logger.info("[PRODAMUS WEBHOOK] Received webhook")
        logger.info(f"[PRODAMUS WEBHOOK] Headers: {dict(request.headers)}")
        logger.info(f"[PRODAMUS WEBHOOK] Body: {data}")
        logger.info(
            f"[PRODAMUS WEBHOOK] Signature: {data.get('signature', 'NO SIGNATURE')}"
        )

        # Извлекаем ключевые параметры
        order_id = data.get("order_id")
        payment_status = data.get("payment_status", "").lower()
        payment_id = data.get("payment_id")
        subscription_id = data.get("subscription_id")
        customer_extra = data.get("customer_extra")  # telegram_id
        signature = data.get("signature")

        # Валидация обязательных полей
        if not all([order_id, payment_status, signature]):
            logger.error("[PRODAMUS WEBHOOK] Missing required fields in webhook data")
            return JsonResponse({"error": "Missing required fields"}, status=400)

        # Проверка подписи для безопасности
        service = ProdamusService()
        is_valid = service.verify_webhook_signature(data, signature)

        if is_valid:
            logger.info(f"[PRODAMUS WEBHOOK] Signature VALID for order {order_id}")
        else:
            logger.warning(f"[PRODAMUS WEBHOOK] Signature INVALID for order {order_id}")
            return JsonResponse({"error": "Invalid signature"}, status=403)

        # Поиск или создание Payment записи
        try:
            payment = Payment.objects.get(order_id=order_id)
            logger.info(f"Found existing payment: {order_id}")
        except Payment.DoesNotExist:
            # Если платеж не найден, пытаемся создать (на случай race condition)
            if not customer_extra:
                logger.error(
                    f"Payment {order_id} not found and no customer_extra provided"
                )
                return JsonResponse({"error": "Payment not found"}, status=404)

            try:
                telegram_id = int(customer_extra)
                profile = TelegramProfile.objects.get(telegram_id=telegram_id)

                # Создаем Payment запись на основе webhook данных
                # Примечание: subscription_plan будет None, его нужно будет установить вручную
                payment = Payment.objects.create(
                    telegram_profile=profile,
                    order_id=order_id,
                    payment_id=payment_id,
                    subscription_id=subscription_id,
                    amount=0,  # Будет обновлено из webhook_data
                    status="pending",
                    webhook_data=data,
                )
                logger.warning(f"Created payment from webhook: {order_id}")
            except (ValueError, TelegramProfile.DoesNotExist) as e:
                logger.error(f"Cannot create payment for order {order_id}: {e}")
                return JsonResponse({"error": "Invalid customer data"}, status=400)

        # Обновляем статус платежа
        old_status = payment.status
        payment.status = payment_status
        payment.payment_id = payment_id or payment.payment_id
        payment.subscription_id = subscription_id or payment.subscription_id
        payment.webhook_data = data

        # При успешной оплате активируем подписку
        if payment_status == "success" and old_status != "success":
            payment.paid_at = timezone.now()

            # Проверяем наличие subscription_plan
            if payment.subscription_plan:
                profile = payment.telegram_profile

                # Активируем подписку
                profile.activate_subscription(payment.subscription_plan)

                logger.info(
                    f"Activated subscription for user {profile.telegram_id}: "
                    f"{payment.subscription_plan.name} "
                    f"(expires: {profile.subscription_expires_at})"
                )
            else:
                logger.error(f"Payment {order_id} has no subscription_plan set")

        payment.save()

        logger.info(
            f"Processed webhook for order {order_id}: "
            f"{old_status} -> {payment_status}"
        )

        # Возвращаем успешный ответ Prodamus
        return JsonResponse(
            {"status": "ok", "order_id": order_id, "payment_status": payment_status}
        )

    except Exception as e:
        logger.exception(f"Error processing webhook: {e}")
        return JsonResponse({"error": "Internal server error"}, status=500)


@require_GET
def prodamus_success(request):
    """Страница успешной оплаты

    Отображается после успешного платежа в Prodamus.
    Пользователь перенаправляется сюда через urlSuccess.
    """
    order_id = request.GET.get("order_id")

    context = {
        "success": True,
        "order_id": order_id,
        "bot_url": settings.PRODAMUS_RETURN_URL,
    }

    # Пытаемся получить информацию о платеже
    if order_id:
        try:
            payment = Payment.objects.get(order_id=order_id)
            context["subscription_name"] = (
                payment.subscription_plan.name if payment.subscription_plan else None
            )
            context["expires_at"] = payment.telegram_profile.subscription_expires_at
            logger.info(f"Success page viewed for order {order_id}")
        except Payment.DoesNotExist:
            logger.warning(f"Payment {order_id} not found on success page")

    return render(request, "bot/payment_success.html", context)
