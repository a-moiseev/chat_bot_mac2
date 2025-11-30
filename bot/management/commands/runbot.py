import asyncio
import logging
import sys

from django.core.management.base import BaseCommand

from bot.services.bot_handlers import MacBot


class Command(BaseCommand):
    help = 'Запуск Telegram бота'

    def handle(self, *args, **options):
        """Запуск бота через Django management command"""
        self.stdout.write(self.style.SUCCESS('Запуск Telegram бота...'))

        # Настройка логирования для консоли
        logging.basicConfig(
            level=logging.INFO,
            stream=sys.stdout,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

        try:
            bot = MacBot()
            self.stdout.write(self.style.SUCCESS('Бот инициализирован, начинаем polling...'))
            asyncio.run(bot.start())
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('\nБот остановлен пользователем'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Ошибка при запуске бота: {e}'))
            raise
