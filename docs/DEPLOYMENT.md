# Развёртывание СЕЙСМОС

Документ описывает варианты развёртывания: systemd, Docker и обратный прокси.

## 1. Вариант: systemd (рекомендуется для объекта)

### Подготовка

```bash
sudo useradd --system --home /opt/seismos --shell /usr/sbin/nologin seismos
sudo mkdir -p /opt/seismos
sudo chown seismos:seismos /opt/seismos
sudo -u seismos git clone <url-репозитория> /opt/seismos
cd /opt/seismos
sudo -u seismos python3 -m venv .venv
sudo -u seismos .venv/bin/pip install -r requirements.txt
```

### Юнит-файл

Скопируйте `deploy/seismos.service` в `/etc/systemd/system/`:

```bash
sudo cp deploy/seismos.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now seismos
```

### Управление

```bash
sudo systemctl status seismos
sudo systemctl restart seismos
sudo journalctl -u seismos -f
```

## 2. Вариант: Docker

### Сборка и запуск

```bash
cd deploy
docker build -t seismos:1.0.0 .
docker run -d --name seismos \
  -p 8000:8000 \
  -v "$(pwd)/../config:/app/config:ro" \
  -v seismos-data:/app/data \
  -e SEISMOS_PORT=8000 \
  seismos:1.0.0
```

### Docker Compose

```bash
cd deploy
docker compose up -d
```

Файлы: `deploy/Dockerfile`, `deploy/docker-compose.yml`.

## 3. Обратный прокси (nginx)

Для публикации консоли и API под HTTPS используйте `deploy/nginx.conf`:

```nginx
server {
    listen 443 ssl;
    server_name seismos.example.ru;

    ssl_certificate     /etc/ssl/seismos/fullchain.pem;
    ssl_certificate_key /etc/ssl/seismos/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ws {
        proxy_pass http://127.0.0.1:8000/ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }
}
```

Важно: для WebSocket-потока обязательны заголовки `Upgrade` и `Connection`,
а также увеличенный `proxy_read_timeout`.

## 4. Сетевые требования

| Направление | Протокол/порт | Назначение |
|---|---|---|
| Узлы сбора → сервер | UDP 4789 | Поток отсчётов |
| Оператор → сервер | TCP 8000 (или 443 через прокси) | REST + WebSocket |
| Сервер → узлы | — | Не требуется (сбор инициируют узлы) |

Если сервер принимает UDP-поток напрямую, откройте порт 4789 в firewall:

```bash
sudo ufw allow 4789/udp
sudo ufw allow 8000/tcp
```

## 5. Контроль работоспособности

- `GET /health` — быстрая проверка живости (используйте в мониторинге).
- `GET /api/v1/status` — состояние системы и оборудования.
- `GET /api/v1/metrics` — метрики для систем мониторинга.

Пример проверки в cron:

```bash
*/1 * * * * curl -sf http://localhost:8000/health >/dev/null || systemctl restart seismos
```

## 6. Масштабирование

- **Несколько узлов сбора** — каждый узел обслуживает свою цепочку; сервер
  принимает потоки от всех узлов.
- **Оптическая магистраль** — между сегментами объекта при большой
  протяжённости.
- **Несколько консолей** — WebSocket-шина поддерживает множество
  одновременных подписчиков; медленные не тормозят обработку.

## 7. Обновление

```bash
cd /opt/seismos
sudo -u seismos git pull
sudo -u seismos .venv/bin/pip install -r requirements.txt
sudo systemctl restart seismos
```

Перед обновлением сделайте резервную копию базы данных (см.
[OPERATIONS.md](OPERATIONS.md)).
