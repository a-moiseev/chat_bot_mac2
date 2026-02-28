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


def _find_profile(customer_extra, prodamus_sub_id):
    """Найти профиль по telegram_id из customer_extra или по subscription_id в платежах"""
    try:
        return TelegramProfile.objects.get(telegram_id=int(customer_extra))
    except (ValueError, TypeError, TelegramProfile.DoesNotExist):
        pass

    if prodamus_sub_id:
        try:
            payment = (
                Payment.objects.filter(subscription_id=prodamus_sub_id)
                .select_related("telegram_profile")
                .latest("created_at")
            )
            return payment.telegram_profile
        except Payment.DoesNotExist:
            pass

    return None


@csrf_exempt
@require_POST
def prodamus_webhook(request):
    """Обработка webhook уведомлений от Prodamus

    Подпись: заголовок Sign
    Наш order_id: поле order_num
    Тип события: subscription[type] (action/notification)
      - action + action_code=auto_payment    → рекуррентное продление
      - notification + notification_code:
          activation                         → активация (пользователь или менеджер)
          deactivation                       → деактивация
          auto_payment_reminder              → напоминание о списании (только лог)
    """
    try:
        data = request.POST.dict()
        signature = request.headers.get("Sign")

        logger.info(
            f"[WEBHOOK] Incoming: order_num={data.get('order_num')!r} "
            f"sub_type={data.get('subscription[type]')!r} "
            f"notification_code={data.get('subscription[notification_code]')!r} "
            f"action_code={data.get('subscription[action_code]')!r} "
            f"sign={'present' if signature else 'missing'}"
        )
        logger.debug(f"[WEBHOOK] Full data: {data}")
        
        # DEBUG: Log raw body for signature debugging (remove after fixing signature issues)
        if settings.DEBUG:
            logger.debug(f"[WEBHOOK] Raw body (first 500 chars): {request.body.decode('utf-8')[:500]}")

        order_num = data.get("order_num")
        customer_extra = data.get("customer_extra", "")
        prodamus_sub_id = data.get("subscription[id]")
        sub_type = data.get("subscription[type]", "")
        notification_code = data.get("subscription[notification_code]", "")
        action_code = data.get("subscription[action_code]", "")
        event_code = action_code if sub_type == "action" else notification_code

        # Первый платёж может прийти без subscription-полей — только с payment_status
        if not event_code:
            payment_status_field = data.get("payment_status", "").lower()
            if payment_status_field == "success":
                event_code = "activation"
            elif payment_status_field in ("failed", "cancelled"):
                event_code = payment_status_field

        if not all([order_num, event_code, signature]):
            logger.error(
                f"[WEBHOOK] Missing required fields: "
                f"order_num={order_num!r} event_code={event_code!r} "
                f"signature={'present' if signature else 'missing'}"
            )
            return JsonResponse({"error": "Missing required fields"}, status=400)

        service = ProdamusService()
        if not service.verify_webhook_signature(request.body, signature):
            logger.warning(f"[WEBHOOK] Invalid signature for order {order_num}")
            return JsonResponse({"error": "Invalid signature"}, status=403)

        # Напоминание о предстоящем списании — только лог, никаких действий
        if event_code == "auto_payment_reminder":
            logger.info(f"[WEBHOOK] Upcoming renewal reminder for order {order_num}")
            return JsonResponse({"status": "ok", "order_id": order_num})

        # Активация подписки (первый платёж, пользователь или менеджер)
        if event_code == "activation":
            initiator = data.get("subscription[initiator]", "user")
            try:
                payment = Payment.objects.get(order_id=order_num)
            except Payment.DoesNotExist:
                logger.warning(
                    f"[WEBHOOK] Payment {order_num} not found for activation "
                    f"(initiator={initiator}), likely test data"
                )
                return JsonResponse({"status": "ok", "order_id": order_num})

            if payment.status != "success":
                payment.paid_at = timezone.now()
                if payment.subscription_plan:
                    payment.telegram_profile.activate_subscription(payment.subscription_plan)
                    logger.info(
                        f"[WEBHOOK] Activated subscription for user "
                        f"{payment.telegram_profile.telegram_id} "
                        f"(initiator={initiator}, "
                        f"expires={payment.telegram_profile.subscription_expires_at})"
                    )
                else:
                    logger.error(f"[WEBHOOK] Payment {order_num} has no subscription_plan")

            payment.status = "success"
            payment.subscription_id = prodamus_sub_id or payment.subscription_id
            payment.webhook_data = data
            payment.save()
            return JsonResponse({"status": "ok", "order_id": order_num})

        # Рекуррентное продление
        if event_code == "auto_payment":
            profile = _find_profile(customer_extra, prodamus_sub_id)
            if profile is None:
                logger.warning(
                    f"[WEBHOOK] Profile not found for renewal order {order_num}, "
                    f"customer_extra={customer_extra!r} — likely test data"
                )
                return JsonResponse({"status": "ok", "order_id": order_num})

            if profile.current_subscription:
                profile.extend_subscription(profile.current_subscription)
                logger.info(
                    f"[WEBHOOK] Extended subscription for user {profile.telegram_id}: "
                    f"{profile.current_subscription.name} "
                    f"(expires={profile.subscription_expires_at})"
                )
            else:
                logger.error(
                    f"[WEBHOOK] No current subscription to extend for user {profile.telegram_id}"
                )
            return JsonResponse({"status": "ok", "order_id": order_num})

        # Деактивация подписки
        if event_code == "deactivation":
            profile = _find_profile(customer_extra, prodamus_sub_id)
            if profile is None:
                logger.warning(
                    f"[WEBHOOK] Profile not found for deactivation order {order_num}, "
                    f"customer_extra={customer_extra!r} — likely test data"
                )
                return JsonResponse({"status": "ok", "order_id": order_num})

            profile.deactivate_subscription()
            logger.info(f"[WEBHOOK] Deactivated subscription for user {profile.telegram_id}")
            return JsonResponse({"status": "ok", "order_id": order_num})

        logger.warning(f"[WEBHOOK] Unknown event_code={event_code!r} for order {order_num}")
        return JsonResponse({"status": "ok", "order_id": order_num})

    except Exception as e:
        logger.exception(f"[WEBHOOK] Error processing webhook: {e}")
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
