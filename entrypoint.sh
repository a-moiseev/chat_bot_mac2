#!/bin/bash

set -e

python manage.py migrate --noinput
python manage.py createcachetable
python manage.py collectstatic --noinput

exec "$@"
