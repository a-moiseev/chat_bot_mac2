# Руководство по миграции данных из mac_bot в mac_bot_2

## Обзор

Этот проект включает инструменты для миграции данных из старой базы данных SQLite проекта `mac_bot` в новую базу данных Django проекта `mac_bot_2`.

## Структура миграции

### Старая база данных (mac_bot)
- **Таблица `users`**: Пользователи Telegram
  - user_id, username, full_name, created_at, last_start

- **Таблица `state_types`**: Типы состояний
  - id, state_name, description, created_at

- **Таблица `user_states`**: Состояния пользователей
  - id, user_id, state_type_id, created_at

### Новая база данных (mac_bot_2)
- **Модель `TelegramProfile`**: Профили пользователей Telegram
- **Модель `StateType`**: Типы состояний
- **Модель `UserState`**: Состояния пользователей
- **Модель `User`**: Стандартная модель пользователя Django

## Предварительные требования

1. Убедитесь, что выполнены все миграции Django:
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

2. Старая база данных должна находиться по пути: `../chat_bot/sqlite.db`
   (или укажите другой путь при запуске)

## Способы миграции

### Способ 1: Использование bash-скрипта (рекомендуется)

#### Пробный запуск (проверка данных без сохранения):
```bash
./migrate_data.sh
```

#### Реальная миграция:
```bash
./migrate_data.sh --migrate
```

### Способ 2: Прямое использование Django команды

#### Пробный запуск:
```bash
python manage.py migrate_from_old_db --source ../chat_bot/sqlite.db --dry-run
```

#### Реальная миграция:
```bash
python manage.py migrate_from_old_db --source ../chat_bot/sqlite.db
```

#### Миграция из другого пути:
```bash
python manage.py migrate_from_old_db --source /path/to/old/database.db
```

## Процесс миграции

Скрипт выполняет миграцию в следующем порядке:

1. **Миграция типов состояний** (`StateType`)
   - Переносятся все типы состояний из таблицы `state_types`
   - Дубликаты пропускаются

2. **Миграция пользователей** (`TelegramProfile`)
   - Для каждого пользователя создается Django `User`
   - Создается связанный `TelegramProfile`
   - Полное имя разделяется на имя и фамилию
   - Если пользователь уже существует, он пропускается

3. **Миграция состояний пользователей** (`UserState`)
   - Переносятся все связи пользователей с состояниями
   - Сохраняются временные метки создания

## Проверка результатов

После миграции проверьте данные в Django shell:

```bash
python manage.py shell
```

```python
from bot.models import TelegramProfile, StateType, UserState

# Проверка количества записей
print(f"Пользователей: {TelegramProfile.objects.count()}")
print(f"Типов состояний: {StateType.objects.count()}")
print(f"Состояний пользователей: {UserState.objects.count()}")

# Просмотр пользователей
for profile in TelegramProfile.objects.all():
    print(f"{profile.telegram_id} - {profile.username} - {profile.first_name} {profile.last_name}")

# Просмотр типов состояний
for state_type in StateType.objects.all():
    print(f"{state_type.state_name}: {state_type.description}")
```

Или через Django admin:
```bash
python manage.py createsuperuser  # если еще не создан
python manage.py runserver
# Откройте http://127.0.0.1:8000/admin/
```

## Безопасность

- Миграция выполняется в **транзакции** - если что-то пойдет не так, все изменения будут откатаны
- Используйте `--dry-run` для проверки данных перед реальной миграцией
- Существующие записи не перезаписываются, только создаются новые

## Особенности миграции

### Преобразование данных пользователей:
- `user_id` → `telegram_id`
- `username` → `username` (если пусто, генерируется `user_{telegram_id}`)
- `full_name` → разделяется на `first_name` и `last_name`
- `created_at` → `created_at`
- `last_start` → `last_request_time`

### Создание Django User:
- Для каждого `TelegramProfile` создается связанный `User`
- Username генерируется как `tg_{telegram_id}`

### Обработка дат:
- Все даты из SQLite конвертируются в timezone-aware datetime
- Используется timezone из настроек Django (`Europe/Moscow`)

## Возможные проблемы и решения

### Ошибка: "Файл базы данных не найден"
- Проверьте путь к старой базе данных
- Укажите правильный путь через параметр `--source`

### Ошибка: "UNIQUE constraint failed"
- Пользователь или состояние уже существует в базе
- Скрипт пропустит дубликаты, это нормально

### Ошибка: "не найден тип состояния"
- Убедитесь, что миграция типов состояний прошла успешно
- Проверьте данные в старой базе

## Откат миграции

Если нужно откатить миграцию:

```bash
# Удалить все мигрированные данные
python manage.py shell
```

```python
from bot.models import TelegramProfile, StateType, UserState
from django.contrib.auth.models import User

# ВНИМАНИЕ: Это удалит все данные!
UserState.objects.all().delete()
TelegramProfile.objects.all().delete()
User.objects.filter(username__startswith='tg_').delete()
StateType.objects.all().delete()
```

## Поддержка

При возникновении проблем проверьте:
1. Логи миграции - скрипт выводит подробную информацию
2. Структуру старой базы данных
3. Настройки Django (timezone, database)
