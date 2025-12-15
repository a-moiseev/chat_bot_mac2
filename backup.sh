#!/bin/bash

DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/opt/chat_bot_mac/backups"
mkdir -p $BACKUP_DIR

docker cp $(docker-compose ps -q django):/app/db.sqlite3 $BACKUP_DIR/db_$DATE.sqlite3

redis-cli --rdb $BACKUP_DIR/redis_$DATE.rdb

docker-compose logs > $BACKUP_DIR/logs_$DATE.log

find $BACKUP_DIR -name "db_*.sqlite3" -mtime +30 -delete
find $BACKUP_DIR -name "redis_*.rdb" -mtime +30 -delete
find $BACKUP_DIR -name "logs_*.log" -mtime +30 -delete

echo "Backup completed: $DATE"
