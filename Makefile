COMPOSE := docker compose

BOOKS_DIR ?= ./books
IMPORT_ROOT ?= /books

.PHONY: up down stop restart build rebuild ps logs logs-backend logs-celery logs-frontend \
        infra shell-backend shell-frontend db-shell redis-shell \
        reset-books reset-es reset-volumes import torch-check

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

stop:
	$(COMPOSE) stop

restart:
	$(COMPOSE) restart

build:
	$(COMPOSE) build

rebuild:
	$(COMPOSE) build --no-cache

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f

logs-backend:
	$(COMPOSE) logs -f backend

logs-celery:
	$(COMPOSE) logs -f celery

logs-frontend:
	$(COMPOSE) logs -f frontend

infra:
	$(COMPOSE) up -d db redis elasticsearch minio minio-init

shell-backend:
	$(COMPOSE) exec backend bash

shell-frontend:
	$(COMPOSE) exec frontend sh

db-shell:
	$(COMPOSE) exec db psql -U libuser -d library

redis-shell:
	$(COMPOSE) exec redis redis-cli

reset-books:
	$(COMPOSE) exec db psql -U libuser -d library -c "TRUNCATE TABLE content_paragraphs, chapters, books RESTART IDENTITY CASCADE;"

reset-es:
	$(COMPOSE) run --rm --no-deps backend python -c "import requests; [print(requests.delete(url).status_code, url) for url in ['http://elasticsearch:9200/books_meta', 'http://elasticsearch:9200/books_content']]"

reset-volumes:
	$(COMPOSE) down -v

import:
	$(COMPOSE) run --rm \
		-v "$(BOOKS_DIR):$(IMPORT_ROOT):ro" \
		backend python build_library_db.py \
		--dsn postgresql://libuser:libpass@db:5432/library \
		--root $(IMPORT_ROOT) \
		--es-url http://elasticsearch:9200 \
		--es-index-meta books_meta \
		--es-index-content books_content \
		--es-use-templates \
		--embed-model /models/bge-m3 \
		--embed-device auto \
		--max-missing-spine 1

torch-check:
	$(COMPOSE) exec celery python -c "import torch; print('torch:', torch.__version__); print('cuda build:', torch.version.cuda); print('cuda available:', torch.cuda.is_available()); print('devices:', torch.cuda.device_count()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no cuda')"

make-admin:
	$(COMPOSE) exec db psql -U libuser -d library -c "UPDATE users SET role = 'admin' WHERE login = 'admin';"
	$(COMPOSE) exec db psql -U libuser -d library -c "SELECT id, login, role FROM users WHERE login = 'admin';"