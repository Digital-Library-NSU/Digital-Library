## 1) Cсылка с EPUB
> https://disk.yandex.ru/d/HKrE-odHqdUEAw

## 2) Структура проекта
Проект запускается через Docker Compose из корня репозитория. Основные директории расположены так:
```text
Digital-Library/
├── backend/
│   ├── app/
│   │   ├── import_epub/
│   │   ├── tasks/
│   │   ├── routers/
│   │   ├── config.py
│   │   └── main.py
│   ├── .venv/                  # окружение в бэкенде а не в корне
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── schema.sql
│   └── build_library_db.py
├── frontend/
├── models/                     #вынесена из бекенда(монтируется отдельно)
│   └── bge-m3/
├── books/                      # именно с таким докер монтирует епабы(для массовой загрузки)
├── docker-compose.yml
└── Makefile
```
## 3) Скачивание модели
### Windows PowerShell

Из корня проекта:

```powershell
mkdir models
python -m pip install huggingface_hub
```

Скачать модель:

```powershell
python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-m3', local_dir='./models/bge-m3', resume_download=True); print('Модель скачана в ./models/bge-m3')"
```
### Linux / macOS

Из корня проекта:

```bash
mkdir -p models
python3 -m pip install huggingface_hub
```

Скачать модель:

```bash
python3 - <<'PY'
from huggingface_hub import snapshot_download

snapshot_download(
    'BAAI/bge-m3',
    local_dir='./models/bge-m3',
    resume_download=True,
)

print('Модель скачана в ./models/bge-m3')
PY
```

## 4) Torch и CUDA
В `backend/Dockerfile` `torch` устанавливается отдельно от остальных зависимостей, чтобы можно было выбрать CPU- или GPU-сборку.

Для GPU используется CUDA-сборка:

```dockerfile
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cu128
```

Если на машине нет NVIDIA GPU / CUDA / GPU-проброса в Docker, можно использовать CPU-сборку:

```dockerfile
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
```
В `docker-compose.yml` это задаётся через build arg:

```yaml
build:
  context: ./backend
  args:
    TORCH_INDEX_URL: https://download.pytorch.org/whl/cu128
```

Для CPU-варианта заменить на:

```yaml
build:
  context: ./backend
  args:
    TORCH_INDEX_URL: https://download.pytorch.org/whl/cpu
```

Если gpu используется в логах celery при загрузке должно появится 
```bash
[INFO] Embedding model loaded: /models/bge-m3, device=cuda
```

## 5) Команды через compose
#### Запустить сервисы:

```powershell
docker compose up -d
```

#### Запустить с пересборкой образов:

```powershell
docker compose up -d --build
```
#### Остановить сервисы:

```powershell
docker compose down
```

#### Сделать пользователя admin администратором

```powershell
docker compose exec db psql -U libuser -d library -c "UPDATE users SET role = 'admin' WHERE login = 'admin'; SELECT id, login, role FROM users WHERE login = 'admin';"
```
#### Массовый импорт книг

EPUB-файлы для массового импорта кладутся в корневую папку `books/`. В контейнере backend она смонтирована как `/books`.

Для запуска скрипта нужны Postgres, Elasticsearch, MinIO и backend-контейнер.

Стандартный запуск через Docker:

```powershell
docker compose up -d db elasticsearch minio backend

docker compose exec backend /bin/bash

python build_library_db.py \
  --root /books \
  --dsn postgresql://libuser:libpass@db:5432/library \
  --es-url http://elasticsearch:9200 \
  --es-index-meta books_meta \
  --es-index-content books_content \
  --embed-model /models/bge-m3 \
  --embed-device auto \
  --embed-batch-size 64 \
  --workers 1 \
  --max-missing-spine 1
```

Параметры подбора:

- `--workers` — количество процессов импорта. Для GPU обычно ставить `1`, потому что каждый процесс загружает свою копию модели. Для CPU можно пробовать `2`, `3`, `4`, если хватает RAM.
- `--embed-device` — где считать embeddings: `auto`, `cuda`, `cpu`.  Для быстрого одиночного импорта на GPU использовать `auto` или `cuda`. Для параллельного CPU-импорта использовать `cpu`.
- `--embed-batch-size` — сколько текстовых окон векторизуется за один проход модели. Качество результата не меняет. Большой batch обычно быстрее, но требует больше памяти. Если  возникает `out of memory`, уменьшать: `64 -> 32 -> 16 -> 8`.

Рекомендуемые варианты:

```powershell
# Быстрый импорт на GPU, один процесс. Если хватает VRAM.
python build_library_db.py --root /books --dsn postgresql://libuser:libpass@db:5432/library --es-url http://elasticsearch:9200 --es-index-meta books_meta --es-index-content books_content --embed-model /models/bge-m3 --embed-device cuda --embed-batch-size 64 --workers 1
```

```powershell
# Более безопасный GPU-импорт при нехватке VRAM.
python build_library_db.py --root /books --dsn postgresql://libuser:libpass@db:5432/library --es-url http://elasticsearch:9200 --es-index-meta books_meta --es-index-content books_content --embed-model /models/bge-m3 --embed-device cuda --embed-batch-size 16 --workers 1
```

```powershell
# CPU-импорт, можно параллелить, но он медленнее.
python build_library_db.py --root /books --dsn postgresql://libuser:libpass@db:5432/library --es-url http://elasticsearch:9200 --es-index-meta books_meta --es-index-content books_content --embed-model /models/bge-m3 --embed-device cpu --embed-batch-size 64 --workers 2
```


