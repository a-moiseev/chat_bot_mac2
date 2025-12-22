from django.core.management.base import BaseCommand

from bot.models import Subscription


class Command(BaseCommand):
    help = "Создать базовые тарифные планы подписки"

    def handle(self, *args, **options):
        subscriptions = [
            {
                "name": "Бесплатный",
                "code": "free",
                "price": 0,
                "duration_days": 999999,
                "daily_sessions_limit": 1,
                "cards_limit": 10,
                "is_active": True,
                "description": "Бесплатный тариф: 1 сессия в день, первые 10 карт из каждой колоды",
            },
            {
                "name": "Месячная премиум",
                "code": "monthly",
                "price": 300,
                "duration_days": 30,
                "daily_sessions_limit": 3,
                "cards_limit": None,
                "is_active": True,
                "description": "Премиум подписка на месяц: 3 сессии в день, все 81 карта",
            },
            {
                "name": "Годовая премиум",
                "code": "yearly",
                "price": 3000,
                "duration_days": 365,
                "daily_sessions_limit": 3,
                "cards_limit": None,
                "is_active": True,
                "description": "Премиум подписка на год: 3 сессии в день, все 81 карта",
            },
        ]

        created_count = 0
        skipped_count = 0

        for sub_data in subscriptions:
            code = sub_data["code"]

            # Проверяем существует ли подписка с таким кодом
            if Subscription.objects.filter(code=code).exists():
                skipped_count += 1
                existing = Subscription.objects.get(code=code)
                self.stdout.write(
                    self.style.WARNING(
                        f"⊝ Пропущен (уже существует): {existing.name} ({existing.code})"
                    )
                )
            else:
                # Создаём только если не существует
                subscription = Subscription.objects.create(**sub_data)
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✓ Создан тариф: {subscription.name} ({subscription.code})"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f'\n{"="*50}\n'
                f"Готово! Создано: {created_count}, Пропущено: {skipped_count}\n"
                f'{"="*50}'
            )
        )

        # Показать все тарифы
        self.stdout.write("\nТекущие тарифы в системе:")
        for sub in Subscription.objects.all():
            status = "✓ Активен" if sub.is_active else "✗ Неактивен"
            self.stdout.write(
                f"  - {sub.name} ({sub.code}): {sub.price}₽, "
                f"{sub.daily_sessions_limit} сессий/день, "
                f"{sub.cards_limit} карт - {status}"
            )
