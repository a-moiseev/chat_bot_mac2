"""
Django management команда для миграции данных из старой базы mac_bot в новую mac_bot_2

Использование:
    python manage.py migrate_from_old_db --source ../chat_bot/sqlite.db
    python manage.py migrate_from_old_db --source ../chat_bot/sqlite.db --dry-run
"""

import sqlite3
from datetime import datetime
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone
from bot.models import TelegramProfile, StateType, UserState


class Command(BaseCommand):
    help = 'Миграция данных из старой базы mac_bot в новую mac_bot_2'

    def add_arguments(self, parser):
        parser.add_argument(
            '--source',
            type=str,
            default='../chat_bot/sqlite.db',
            help='Путь к старой базе данных SQLite (по умолчанию: ../chat_bot/sqlite.db)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Пробный запуск без сохранения данных в базу'
        )

    def handle(self, *args, **options):
        source_db = options['source']
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('РЕЖИМ ПРОБНОГО ЗАПУСКА - данные не будут сохранены'))

        try:
            # Подключаемся к старой базе данных
            conn = sqlite3.connect(source_db)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            self.stdout.write(self.style.SUCCESS(f'Подключено к базе: {source_db}'))

            # Проверяем наличие таблиц
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            self.stdout.write(f'Найденные таблицы: {", ".join(tables)}')

            # Получаем статистику
            stats = self._get_stats(cursor)
            self.stdout.write(self.style.SUCCESS('\nСтатистика старой базы:'))
            self.stdout.write(f'  Пользователей: {stats["users"]}')
            self.stdout.write(f'  Типов состояний: {stats["state_types"]}')
            self.stdout.write(f'  Состояний пользователей: {stats["user_states"]}')

            if not dry_run:
                # Начинаем миграцию в транзакции
                with transaction.atomic():
                    self.stdout.write(self.style.SUCCESS('\n--- НАЧАЛО МИГРАЦИИ ---\n'))

                    # Шаг 1: Миграция типов состояний
                    state_types_count = self._migrate_state_types(cursor)
                    self.stdout.write(self.style.SUCCESS(f'✓ Мигрировано типов состояний: {state_types_count}'))

                    # Шаг 2: Миграция пользователей
                    users_count = self._migrate_users(cursor)
                    self.stdout.write(self.style.SUCCESS(f'✓ Мигрировано пользователей: {users_count}'))

                    # Шаг 3: Миграция состояний пользователей
                    user_states_count = self._migrate_user_states(cursor)
                    self.stdout.write(self.style.SUCCESS(f'✓ Мигрировано состояний: {user_states_count}'))

                    self.stdout.write(self.style.SUCCESS('\n--- МИГРАЦИЯ ЗАВЕРШЕНА УСПЕШНО ---'))
            else:
                # Пробный запуск - просто показываем данные
                self._show_sample_data(cursor)

            conn.close()

        except sqlite3.Error as e:
            raise CommandError(f'Ошибка при работе с базой данных: {e}')
        except Exception as e:
            raise CommandError(f'Ошибка миграции: {e}')

    def _get_stats(self, cursor):
        """Получить статистику по старой базе"""
        stats = {}

        cursor.execute("SELECT COUNT(*) FROM users")
        stats['users'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM state_types")
        stats['state_types'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM user_states")
        stats['user_states'] = cursor.fetchone()[0]

        return stats

    def _show_sample_data(self, cursor):
        """Показать примеры данных для пробного запуска"""
        self.stdout.write(self.style.WARNING('\n--- ПРИМЕРЫ ДАННЫХ (DRY RUN) ---\n'))

        # Показываем пользователей
        cursor.execute("SELECT * FROM users LIMIT 5")
        self.stdout.write('Примеры пользователей:')
        for row in cursor.fetchall():
            self.stdout.write(f'  - ID: {row["user_id"]}, Username: {row["username"]}, Name: {row["full_name"]}')

        # Показываем типы состояний
        cursor.execute("SELECT * FROM state_types")
        self.stdout.write('\nТипы состояний:')
        for row in cursor.fetchall():
            self.stdout.write(f'  - {row["state_name"]}: {row["description"]}')

    def _migrate_state_types(self, cursor):
        """Миграция типов состояний"""
        cursor.execute("SELECT * FROM state_types")
        state_types = cursor.fetchall()

        count = 0
        for row in state_types:
            # Проверяем, существует ли уже такой тип состояния
            state_type, created = StateType.objects.get_or_create(
                state_name=row['state_name'],
                defaults={
                    'description': row['description'],
                    'created_at': self._parse_datetime(row['created_at'])
                }
            )
            if created:
                count += 1
                self.stdout.write(f'  + Создан тип состояния: {state_type.state_name}')
            else:
                self.stdout.write(f'  = Тип состояния уже существует: {state_type.state_name}')

        return count

    def _migrate_users(self, cursor):
        """Миграция пользователей"""
        cursor.execute("SELECT * FROM users")
        users = cursor.fetchall()

        count = 0
        for row in users:
            telegram_id = row['user_id']
            username = row['username'] or f'user_{telegram_id}'
            full_name = row['full_name'] or ''

            # Разделяем полное имя на имя и фамилию
            name_parts = full_name.split(' ', 1)
            first_name = name_parts[0] if len(name_parts) > 0 else ''
            last_name = name_parts[1] if len(name_parts) > 1 else ''

            # Проверяем, существует ли уже пользователь с таким telegram_id
            if TelegramProfile.objects.filter(telegram_id=telegram_id).exists():
                self.stdout.write(f'  = Пользователь уже существует: {telegram_id} (@{username})')
                continue

            # Создаем Django User
            django_user = User.objects.create_user(
                username=f'tg_{telegram_id}',
                first_name=first_name[:30],  # Django ограничивает длину
                last_name=last_name[:150]
            )

            # Создаем TelegramProfile
            created_at = self._parse_datetime(row['created_at'])
            last_request = self._parse_datetime(row['last_start'])

            telegram_profile = TelegramProfile.objects.create(
                user=django_user,
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                created_at=created_at,
                last_request_time=last_request
            )

            count += 1
            self.stdout.write(f'  + Создан пользователь: {telegram_id} (@{username})')

        return count

    def _migrate_user_states(self, cursor):
        """Миграция состояний пользователей"""
        cursor.execute("""
            SELECT us.*, st.state_name
            FROM user_states us
            JOIN state_types st ON us.state_type_id = st.id
        """)
        user_states = cursor.fetchall()

        count = 0
        for row in user_states:
            telegram_id = row['user_id']
            state_name = row['state_name']

            try:
                # Находим соответствующий TelegramProfile
                telegram_profile = TelegramProfile.objects.get(telegram_id=telegram_id)

                # Находим тип состояния
                state_type = StateType.objects.get(state_name=state_name)

                # Создаем состояние пользователя
                created_at = self._parse_datetime(row['created_at'])

                UserState.objects.create(
                    telegram_profile=telegram_profile,
                    state_type=state_type,
                    created_at=created_at
                )

                count += 1

            except TelegramProfile.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(f'  ! Пропущено состояние: пользователь {telegram_id} не найден')
                )
            except StateType.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(f'  ! Пропущено состояние: тип "{state_name}" не найден')
                )

        return count

    def _parse_datetime(self, dt_string):
        """Парсинг datetime из строки SQLite"""
        if not dt_string:
            return timezone.now()

        try:
            # Пробуем разные форматы
            for fmt in ['%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d']:
                try:
                    dt = datetime.strptime(dt_string, fmt)
                    # Делаем datetime aware (timezone-aware)
                    return timezone.make_aware(dt, timezone.get_current_timezone())
                except ValueError:
                    continue

            # Если ничего не подошло, возвращаем текущее время
            return timezone.now()

        except Exception:
            return timezone.now()
