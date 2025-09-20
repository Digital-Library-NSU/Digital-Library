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
sudo docker run --name es8 -p 9200:9200 -p 9300:9300 \
  -e discovery.type=single-node \
  -e xpack.security.enabled=false \
  -e ES_JAVA_OPTS="-Xms2g -Xmx2g" \
  -v esdata:/usr/share/elasticsearch/data \
  docker.elastic.co/elasticsearch/elasticsearch:8.14.1
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
## 5) Импорт EPUB в БД + ES
```
pip install -r requirements.txt
```
```
python build_library_db.py \
  --dsn postgresql://libuser:libpass@localhost:5432/library \
  --root <ВАШ_ПУТЬ_К_EPUB_ПАПКЕ> \
  --create-db --recreate-schema \
  --es-url http://localhost:9200 \
  --es-use-templates --es-enable-suggest \
  --chunk-words 800 --chunk-overlap 80
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