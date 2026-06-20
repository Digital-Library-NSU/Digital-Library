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

```powershell
docker compose exec backend /bin/bash

python build_library_db.py \
  --root /books \
  --dsn postgresql://libuser:libpass@db:5432/library \
  --es-url http://elasticsearch:9200 \
  --es-index-meta books_meta \
  --es-index-content books_content \
  --embed-model /models/bge-m3 \
  --embed-device auto \
  --max-missing-spine 1
```

