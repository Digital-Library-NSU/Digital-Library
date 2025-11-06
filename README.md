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

## 5) Импорт EPUB в БД + ES
```
pip install -r requirements.txt
```
Если есть CUDA
```
pip install -r requirements.txt --index-url https://download.pytorch.org/whl/cu121
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

```
python build_library_db.py \
  --dsn postgresql://libuser:libpass@localhost:5432/library \
  --root  <ВАШ_ПУТЬ_К_EPUB_ПАПКЕ> \
  --es-url http://localhost:9200 \
  --es-index-meta books_meta \
  --es-index-content books_content \
  --es-use-templates \
  --es-dense-vector-dim 1024 \
  --join-short-paragraphs --min-paragraph-words 15 \
  --para-window-size 2 --para-window-stride 1 \
  --embed-model ./models/bge-m3 \
  --embed-device auto \
  --embed-batch-size 64 \
  --embed-max-words 256 --embed-overlap-words 32 \
  --embed-normalize \
  --limit 10 #на cpu даже 10 первых книг будут векторизоваться долго
```
## 6) Как открыть базу в DBeaver
1. Database → New Database Connection → PostgreSQL
2. Параметры:
   * Host: localhost
   * Port: 5432
   * Database: library
   * Username: libuser
   * Password: libpass
   * SSL: Disabled
3. Test Connection → Finish.   

## 7) Запуск бекенда и примеры запросов в Postman
```
uvicorn app:app --reload --port 8000
```

Проверка:
```
GET http://localhost:8000/health
```
Поиск по названию:
```
GET http://localhost:8000/books/search?q=Анна%20Коренина&size=5
```
(ошибка в фамилии специально - найдет)

Поиск по цитате:
```
GET http://localhost:8000/quotes/search?q=Все%20смешалось%20в%20доме%20Облонских&slop=2&size=5
```

Семантический поиск:
```
GET http://localhost:8000/semantic/search?q=книга%20про%20женщину&size=5
```