#!/bin/bash

# Скрипт для миграции данных из старой базы mac_bot в новую mac_bot_2
# Использование:
#   ./migrate_data.sh             - пробный запуск (dry-run)
#   ./migrate_data.sh --migrate   - выполнить реальную миграцию

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Путь к старой базе данных
OLD_DB="../chat_bot/sqlite.db"

echo -e "${GREEN}=== Скрипт миграции данных mac_bot -> mac_bot_2 ===${NC}\n"

# Проверяем существование старой базы
if [ ! -f "$OLD_DB" ]; then
    echo -e "${RED}ОШИБКА: Файл базы данных не найден: $OLD_DB${NC}"
    echo "Укажите правильный путь к старой базе данных"
    exit 1
fi

# Проверяем параметры
if [ "$1" == "--migrate" ]; then
    echo -e "${YELLOW}ВНИМАНИЕ: Будет выполнена реальная миграция данных!${NC}"
    echo -e "${YELLOW}Убедитесь, что вы выполнили миграции Django:${NC}"
    echo -e "  python manage.py makemigrations"
    echo -e "  python manage.py migrate\n"

    read -p "Продолжить миграцию? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        echo -e "${RED}Миграция отменена${NC}"
        exit 0
    fi

    echo -e "\n${GREEN}Выполняется миграция...${NC}\n"
    python manage.py migrate_from_old_db --source "$OLD_DB"

    if [ $? -eq 0 ]; then
        echo -e "\n${GREEN}✓ Миграция завершена успешно!${NC}"
        echo -e "\nПроверьте данные:"
        echo -e "  python manage.py shell"
        echo -e "  >>> from bot.models import TelegramProfile, StateType, UserState"
        echo -e "  >>> TelegramProfile.objects.count()"
        echo -e "  >>> StateType.objects.count()"
        echo -e "  >>> UserState.objects.count()"
    else
        echo -e "\n${RED}✗ Ошибка при миграции!${NC}"
        exit 1
    fi
else
    echo -e "${YELLOW}Режим пробного запуска (DRY RUN)${NC}"
    echo -e "Для выполнения реальной миграции используйте: $0 --migrate\n"

    python manage.py migrate_from_old_db --source "$OLD_DB" --dry-run
fi
