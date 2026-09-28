# Развёртывание на сервере (gunicorn + nginx + PostgreSQL)

Полный порядок запуска приложения на Linux-сервере с нуля. Если gunicorn и nginx у вас уже настроены и работают (например, раньше приложение крутилось на SQLite) — просто пропустите шаги 5 и 7, а с шага 3 выполните только перенос на PostgreSQL и перезапуск сервиса.

Везде ниже замените:
- `/opt/uchet` — на реальный путь к проекту на сервере,
- `deploy` — на реального системного пользователя, от которого будет работать приложение,
- `uchet.example.com` — на реальный домен (или IP-адрес сервера, если домена нет),
- `придумайте-пароль` — на настоящий пароль для БД.

## 1. Код проекта

```bash
sudo mkdir -p /opt/uchet
sudo chown $USER:$USER /opt/uchet
git clone <адрес-вашего-репозитория> /opt/uchet
cd /opt/uchet
```
(если код уже на сервере — просто `cd /opt/uchet && git pull`)

## 2. Python-окружение

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install gunicorn
```

## 3. PostgreSQL

```bash
sudo apt update
sudo apt install -y postgresql postgresql-contrib
sudo systemctl enable --now postgresql
sudo -u postgres psql
```
```sql
CREATE USER uchet WITH PASSWORD 'придумайте-пароль';
CREATE DATABASE uchet OWNER uchet;
\q
```

Порт 5432 наружу не открываем — PostgreSQL слушает только `localhost`, этого достаточно (приложение и БД на одном сервере).

## 4. Схема БД и перенос данных из старого db.db

Один непрерывный терминал-сеанс (переменная окружения нужна для обеих команд подряд):

```bash
export DATABASE_URL="postgresql://uchet:придумайте-пароль@localhost:5432/uchet"
python database.py                                     # создаёт все таблицы
cp db.db db.db.backup_before_postgres                   # если раньше уже был SQLite-файл с данными
python migrate_data_to_postgres.py db.db.backup_before_postgres
```

Если это первый запуск и старых данных нет — шаг с `migrate_data_to_postgres.py` не нужен, `python database.py` сам создаст пустую схему с дефолтным пользователем `admin` / `admin123` (обязательно смените пароль после первого входа).

Скрипт переноса в конце печатает сверку строк по каждой таблице — убедитесь, что везде `OK`.

## 5. Gunicorn как systemd-сервис

Создайте `/etc/systemd/system/uchet.service`:

```ini
[Unit]
Description=uchet gunicorn service
After=network.target postgresql.service

[Service]
User=deploy
Group=www-data
WorkingDirectory=/opt/uchet
Environment=DATABASE_URL=postgresql://uchet:придумайте-пароль@localhost:5432/uchet
ExecStart=/opt/uchet/venv/bin/gunicorn --workers 3 --bind unix:/opt/uchet/uchet.sock app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

`--workers 3` — стартовое значение, ориентир: `(2 × число ядер) + 1`. Каждый воркер — отдельный процесс с собственным соединением к PostgreSQL, поэтому в отличие от старого SQLite-файла увеличение числа воркеров больше не проблема.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now uchet
sudo systemctl status uchet
```

Проверить, что сокет появился: `ls -la /opt/uchet/uchet.sock`

## 6. Права на статику и загрузки

Фото оборудования сохраняются в `static/uploads/equipment/` внутри проекта — процесс gunicorn должен иметь право туда писать:

```bash
sudo mkdir -p /opt/uchet/static/uploads/equipment
sudo chown -R deploy:www-data /opt/uchet/static
sudo chmod -R 775 /opt/uchet/static
```

## 7. nginx как обратный прокси

Создайте `/etc/nginx/sites-available/uchet`:

```nginx
server {
    listen 80;
    server_name uchet.example.com;

    client_max_body_size 10M;   # с запасом под фото оборудования (лимит в приложении — 8MB)

    location /static/ {
        alias /opt/uchet/static/;
    }

    location / {
        proxy_pass http://unix:/opt/uchet/uchet.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/uchet /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

Для HTTPS проще всего Let's Encrypt через certbot:
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d uchet.example.com
```
(certbot сам допишет `listen 443 ssl` и редирект с 80 на 443 в конфиг)

## 8. Проверка

```bash
sudo systemctl status uchet nginx
journalctl -u uchet -f
```

Откройте `http://uchet.example.com` (или `https://`, если настроили certbot) в браузере — должна открыться страница входа, а после логина — данные, перенесённые из старой SQLite-базы.

## Обновление кода в будущем

```bash
cd /opt/uchet
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart uchet
```

## Откат, если что-то пошло не так

1. `git log`, найти коммит до перехода на PostgreSQL, откатить код (`git checkout <коммит>` или восстановить `app.py`/`database.py` из бэкапа).
2. `db.db` (или `db.db.backup_before_postgres`) не удалялся — старая SQLite-версия кода сразу заработает с ним.
3. `sudo systemctl restart uchet`

## Как посмотреть данные в PostgreSQL напрямую (без приложения)

См. раздел «Как смотреть данные в PostgreSQL не через приложение» в [DEPLOY_POSTGRES.md](DEPLOY_POSTGRES.md) — psql на самом сервере, либо pgAdmin/DBeaver с вашего компьютера через SSH-туннель.
