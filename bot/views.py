import logging
from urllib.parse import urlparse

from asgiref.sync import async_to_sync
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django_ratelimit.decorators import ratelimit

from bot.models import Payment, Subscription, TelegramProfile
from bot.services.payment_token import validate_payment_token
from bot.services.prodamus_service import ProdamusService

logger = logging.getLogger("mac_bot")

# Allowed domains for payment redirects
ALLOWED_PAYMENT_DOMAINS = (
    "payform.ru",
    "prodamus.ru",
)


def _render_invalid_link_error(request):
    """Render generic error page for invalid/expired token or user not found"""
    return render(
        request,
        "bot/payment_error.html",
        {
            "title": "Ссылка недействительна",
            "message": "Срок действия ссылки истек или она недействительна. "
            "Пожалуйста, запросите новую ссылку в боте командой /subscribe.",
            "bot_url": settings.PRODAMUS_RETURN_URL,
        },
    )


def _is_valid_payment_url(url: str) -> bool:
    """Validate that payment URL belongs to allowed domains"""
    try:
        parsed = urlparse(url)
        return any(
            parsed.netloc == domain or parsed.netloc.endswith(f".{domain}")
            for domain in ALLOWED_PAYMENT_DOMAINS
        )
    except Exception:
        return False


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
    logger.info(
        f"[WEBHOOK] Incoming request: method={request.method} "
        f"content_type={request.content_type} "
        f"headers={dict(request.headers)}"
    )
    logger.info(f"[WEBHOOK] POST data: {request.POST.dict()}")

    try:
        # Парсим данные из POST запроса
        data = request.POST.dict()

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

        if not is_valid:
            logger.warning(f"[PRODAMUS WEBHOOK] Invalid signature for order {order_id}")
            return JsonResponse({"error": "Invalid signature"}, status=403)

        # Поиск или создание Payment записи
        try:
            payment = Payment.objects.get(order_id=order_id)
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


@ratelimit(key="ip", rate="30/m", block=True)
@require_GET
def subscription_info(request, token):
    """Страница информации о подписке пользователя"""
    token_data = validate_payment_token(token)
    if not token_data:
        return _render_invalid_link_error(request)

    telegram_id = token_data.get("telegram_id")
    username = token_data.get("username", "")

    try:
        profile = TelegramProfile.objects.select_related("current_subscription").get(
            telegram_id=telegram_id
        )
    except TelegramProfile.DoesNotExist:
        return _render_invalid_link_error(request)

    context = {
        "token": token,
        "username": username,
        "profile": profile,
        "is_premium": profile.is_subscribed,
    }
    return render(request, "bot/subscription_info.html", context)


@ratelimit(key="ip", rate="30/m", block=True)
@require_GET
def payment_select(request, token):
    """Страница выбора тарифа

    Отображает доступные тарифы и позволяет пользователю выбрать план.
    Токен содержит telegram_id пользователя для идентификации.
    """
    # Валидация токена
    token_data = validate_payment_token(token)
    if not token_data:
        logger.warning("[PAYMENT_SELECT] Invalid or expired token")
        return _render_invalid_link_error(request)

    telegram_id = token_data.get("telegram_id")
    username = token_data.get("username")

    # Проверяем существование профиля
    try:
        profile = TelegramProfile.objects.get(telegram_id=telegram_id)
    except TelegramProfile.DoesNotExist:
        logger.warning(f"[PAYMENT_SELECT] Profile not found for token")
        return _render_invalid_link_error(request)

    # Сохраняем данные пользователя в сессию, чтобы payment_process не требовал токен повторно
    request.session['payment_telegram_id'] = telegram_id
    request.session['payment_username'] = username

    # Получаем активные тарифы (кроме free)
    plans = (
        Subscription.objects.filter(is_active=True)
        .exclude(code="free")
        .order_by("price")
    )

    context = {
        "token": token,
        "username": username,
        "plans": plans,
        "user_email": profile.email,
    }

    return render(request, "bot/payment_select.html", context)


@ratelimit(key="ip", rate="10/m", block=True)
@require_POST
def payment_process(request, token):
    """Обработка выбора тарифа и создание платежа

    Создает Payment запись в БД и перенаправляет на Prodamus для оплаты.
    """
    # Читаем данные пользователя из сессии (установлены при открытии payment_select)
    telegram_id = request.session.get('payment_telegram_id')
    username = request.session.get('payment_username', '')
    if not telegram_id:
        logger.warning("[PAYMENT_PROCESS] No session data, token was never validated")
        return _render_invalid_link_error(request)

    # Получаем выбранный тариф
    plan_code = request.POST.get("plan_code")
    if not plan_code:
        logger.warning("[PAYMENT_PROCESS] No plan_code in request")
        return render(
            request,
            "bot/payment_error.html",
            {
                "title": "Тариф не выбран",
                "message": "Пожалуйста, выберите тариф.",
                "bot_url": settings.PRODAMUS_RETURN_URL,
            },
        )

    logger.info(f"[PAYMENT_PROCESS] User {telegram_id} selected plan: {plan_code}")

    # Проверяем существование профиля
    try:
        profile = TelegramProfile.objects.get(telegram_id=telegram_id)
    except TelegramProfile.DoesNotExist:
        logger.warning("[PAYMENT_PROCESS] Profile not found for token")
        return _render_invalid_link_error(request)

    # Получаем email из формы или профиля
    import re

    email = request.POST.get("email", "").strip().lower()
    email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"

    if email:
        # Валидация email если передан из формы
        if not re.match(email_pattern, email):
            logger.warning(f"[PAYMENT_PROCESS] Invalid email format for user {telegram_id}")
            return render(
                request,
                "bot/payment_error.html",
                {
                    "title": "Некорректный email",
                    "message": "Пожалуйста, введите корректный email адрес.",
                    "bot_url": settings.PRODAMUS_RETURN_URL,
                },
            )
        # Сохраняем email в профиль
        profile.email = email
        profile.save(update_fields=["email", "updated_at"])
        logger.info(f"[PAYMENT_PROCESS] Saved email for user {telegram_id}")
    else:
        # Используем email из профиля
        email = profile.email

    # Проверяем наличие email
    if not email:
        logger.warning(f"[PAYMENT_PROCESS] No email for user {telegram_id}")
        return render(
            request,
            "bot/payment_error.html",
            {
                "title": "Email обязателен",
                "message": "Пожалуйста, укажите email для получения чека.",
                "bot_url": settings.PRODAMUS_RETURN_URL,
            },
        )

    # Получаем тарифный план
    prodamus = ProdamusService()
    subscription_plan = prodamus.get_subscription_by_code(plan_code)
    if not subscription_plan:
        logger.warning(f"[PAYMENT_PROCESS] Invalid plan_code: {plan_code}")
        return render(
            request,
            "bot/payment_error.html",
            {
                "title": "Тариф не найден",
                "message": "Выбранный тариф не найден или недоступен.",
                "bot_url": settings.PRODAMUS_RETURN_URL,
            },
        )

    # Генерируем order_id и создаем Payment
    order_id = prodamus.generate_order_id(telegram_id, plan_code)

    payment = Payment.objects.create(
        telegram_profile=profile,
        subscription_plan=subscription_plan,
        order_id=order_id,
        amount=subscription_plan.price,
        status="pending",
        customer_email=email,
    )

    logger.info(f"[PAYMENT_PROCESS] Created payment {order_id}")

    # Создаем ссылку на оплату через Prodamus
    try:
        payment_url = async_to_sync(prodamus.create_payment_link)(
            order_id=order_id,
            subscription_plan=subscription_plan,
            user_id=telegram_id,
            username=username,
            email=email,
        )

        # Validate payment URL to prevent open redirect
        if not _is_valid_payment_url(payment_url):
            logger.error(f"[PAYMENT_PROCESS] Invalid payment URL domain for order {order_id}")
            payment.delete()
            return render(
                request,
                "bot/payment_error.html",
                {
                    "title": "Ошибка создания платежа",
                    "message": "Не удалось создать ссылку на оплату. "
                    "Пожалуйста, попробуйте позже или обратитесь в поддержку.",
                    "bot_url": settings.PRODAMUS_RETURN_URL,
                },
            )

        logger.info(f"[PAYMENT_PROCESS] Redirecting to Prodamus")
        return redirect(payment_url)

    except Exception as e:
        logger.exception("[PAYMENT_PROCESS] Failed to create payment link")
        # Удаляем созданный платеж при ошибке
        payment.delete()
        return render(
            request,
            "bot/payment_error.html",
            {
                "title": "Ошибка создания платежа",
                "message": "Не удалось создать ссылку на оплату. "
                "Пожалуйста, попробуйте позже или обратитесь в поддержку.",
                "bot_url": settings.PRODAMUS_RETURN_URL,
            },
        )
