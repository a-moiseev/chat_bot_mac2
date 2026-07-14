import sys

from django.core.management.base import BaseCommand

from bot.services import heartbeat


class Command(BaseCommand):
    help = "Проверка пульса бота для docker healthcheck: exit 0 - жив, exit 1 - залип"

    def handle(self, *args, **options):
        ok, details = heartbeat.check()

        if ok:
            self.stdout.write(self.style.SUCCESS(f"ok: {details['last_tick']}"))
            return

        self.stderr.write(self.style.ERROR(f"unhealthy: {details['problems']}"))
        sys.exit(1)
