## 1) Cсылка с EPUB
> https://disk.yandex.ru/d/HKrE-odHqdUEAw

## 2) Установка DBeaver CE
> https://dbeaver.io/download/

Ubuntu (через snap):
```bash
sudo snap install dbeaver-ce
```

## 3) PostgreSQL: установка и создание БД/пользователя
Установить и запустить:
```bash
sudo apt update
sudo apt install -y postgresql postgresql-contrib
sudo systemctl enable postgresql
sudo systemctl start postgresql
```
Создать пользователя и базу:
```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE libuser WITH LOGIN PASSWORD 'libpass';
CREATE DATABASE library OWNER libuser;
GRANT ALL PRIVILEGES ON DATABASE library TO libuser;
\q
SQL
```
DSN для дальнейших команд: 
> postgresql://libuser:libpass@localhost:5432/library

## 4) Elasticsearch (Docker)
Запускать без vpn

Первый запуск:
```bash
docker pull elastic/elasticsearch:8.14.1
sudo docker run --name es8 -p 9200:9200 -p 9300:9300 \
  -e discovery.type=single-node \
  -e xpack.security.enabled=false \
  -e ES_JAVA_OPTS="-Xms2g -Xmx2g" \
  -v esdata:/usr/share/elasticsearch/data \
  elastic/elasticsearch:8.14.1
```
Впоследующем:
```bash
sudo docker start es8
```
Проверка:
```bash
curl http://localhost:9200
```
Должно быть че то типо(может не сразу появляться, немного подождать надо):
```
{
  "name" : "8c2cb0de17f0",
  "cluster_name" : "docker-cluster",
  "cluster_uuid" : "3Hz68rApRoW0qJQ-NBAX7A",
  "version" : {
    "number" : "8.14.1",
    "build_flavor" : "default",
    "build_type" : "docker",
    "build_hash" : "93a57a1a76f556d8aee6a90d1a95b06187501310",
    "build_date" : "2024-06-10T23:35:17.114581191Z",
    "build_snapshot" : false,
    "lucene_version" : "9.10.0",
    "minimum_wire_compatibility_version" : "7.17.0",
    "minimum_index_compatibility_version" : "7.0.0"
  },
  "tagline" : "You Know, for Search"
}
```
ВАЖНО: если до введения векторизации уже запускали контейнер, то при запущенном контейнере в другом терминале
```
curl -XDELETE http://localhost:9200/books_content
curl -XDELETE http://localhost:9200/_index_template/books_content_templateooks_content_template
```
а потом уже запускать скрипт

## 5) Minio
первый запуск
```bash
docker run -d \
  --name library-minio \
  -p 9000:9000 \
  -p 9001:9001 \
  -e MINIO_ROOT_USER=minioadmin \
  -e MINIO_ROOT_PASSWORD=minioadmin \
  -v "$PWD/minio_data:/data" \
  minio/minio server /data --console-address ":9001"
```
MinIO console:
http://localhost:9001

Логин/пароль:
minioadmin
minioadmin

```bash
docker start library-minio
```

## 6) Redis
первый запуск
```bash
docker run -d \
  --name library-redis \
  -p 6379:6379 \
  redis:7
```

```bash
docker start library-redis
```

## 7) Импорт EPUB в БД + ES
```
pip install -r requirements.txt
```

Скачтать модель(получилось только так)
```
pip install -U huggingface_hub
python - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download('BAAI/bge-m3', local_dir='./models/bge-m3', resume_download=True)
print("Модель скачана в ./models/bge-m3")
PY
```
на последнем проценте подвиснит это ок

если postrges dsn, es url, export-root и embend model совпадают с env
```
python build_library_db.py \
  --create-db --recreate-schema \
  --root  <ВАШ_ПУТЬ_К_EPUB_ПАПКЕ> \
  --recreate-es \ не удалит таблицы аутентификации
  --es-use-templates \
  --workers <если нужен параллелизм, по дефолту 1> \
  --limit 5 #на cpu даже 5 первых книг будут векторизоваться долго
```
## 8) Как открыть базу в DBeaver
1. Database → New Database Connection → PostgreSQL
2. Параметры:
   * Host: localhost
   * Port: 5432
   * Database: library
   * Username: libuser
   * Password: libpass
   * SSL: Disabled
3. Test Connection → Finish.   

## 9) Запуск бекенда и примеры запросов 
```
uvicorn app.main:app --reload #из папки backend
```

Celery
```
celery -A app.celery_app.celery_app worker --loglevel=info --concurrency=1
```

Проверка:
```
curl http://localhost:8000/health
```
Поиск по названию:
```
curl -G 'http://localhost:8000/search/fulltext' \
  --data-urlencode 'q=Избраные' \
  --data-urlencode 'size=10' \
  --data-urlencode 'offset=0' | jq
```

Поиск по цитате:
```
curl -G 'http://localhost:8000/search/fulltext' \
  --data-urlencode 'q=Живите счастливо' \
  --data-urlencode 'size=10' \
  --data-urlencode 'offset=0' | jq
```

Семантический поиск:
```
curl -G 'http://localhost:8000/search/semantic' \
  --data-urlencode 'q=про пагоду' \
  --data-urlencode 'size=10' \
  --data-urlencode 'offset=0' | jq
```

Список книг
```
curl "http://localhost:8000/books/all" | jq
```

Карточка книги
```
curl "http://localhost:8000/books/1" | jq
```

Загруузка книги
```
curl -X POST "http://localhost:8000/books/upload" \
  -F "file=@<путь к epub>"
```