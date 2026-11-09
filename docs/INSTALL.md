# Установка и настройка СЕЙСМОС

## 1. Требования

- Python 3.11 или новее;
- операционная система: Linux (рекомендуется), macOS, Windows;
- 1 ГБ ОЗУ и 1 ГБ дискового пространства для серверной части;
- сетевой доступ к узлам сбора (UDP).

Зависимости (см. `requirements.txt`): `fastapi`, `uvicorn[standard]`,
`pydantic`, `pydantic-settings`, `PyYAML`, `numpy`.

## 2. Установка

### Вариант A: из репозитория

```bash
git clone <url-репозитория> seismos
cd seismos
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Вариант B: как пакет (даёт команду `seismos`)

```bash
pip install -e .
```

С дополнительными зависимостями для разработки:

```bash
pip install -e ".[dev]"
```

Для работы с аппаратным SPI (одноплатные узлы):

```bash
pip install -e ".[hardware]"
```

## 3. Первый запуск

```bash
seismos serve --host 0.0.0.0 --port 8000
```

Проверка:

```bash
curl http://localhost:8000/health
# {"status":"ok","version":"1.0.0","ts":...}
```

Консоль оператора: <http://localhost:8000/>.
Документация API (Swagger UI): <http://localhost:8000/docs>.

## 4. Настройка окружения

Настройки читаются из переменных окружения с префиксом `SEISMOS_` и/или из
файла `.env` в рабочем каталоге.

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `SEISMOS_HOST` | `0.0.0.0` | Адрес прослушивания |
| `SEISMOS_PORT` | `8000` | Порт |
| `SEISMOS_SITE_CONFIG` | `config/site.yaml` | Путь к конфигурации объекта |
| `SEISMOS_DATABASE_URL` | `sqlite:///data/seismos.db` | URL базы данных |
| `SEISMOS_DATA_DIR` | `data` | Каталог данных и записей |
| `SEISMOS_LOG_LEVEL` | `INFO` | Уровень логирования |
| `SEISMOS_AUTH_TOKEN` | — | Токен доступа к API (если задан) |
| `SEISMOS_ALLOW_SIM` | `true` | Разрешить стендовые вставки |
| `SEISMOS_RETENTION_DAYS` | `30` | Срок хранения событий |
| `SEISMOS_CORS_ORIGINS` | `["*"]` | Разрешённые источники CORS |

Пример `.env`:

```dotenv
SEISMOS_PORT=8000
SEISMOS_AUTH_TOKEN=change-me
SEISMOS_SITE_CONFIG=config/site.yaml
SEISMOS_DATABASE_URL=sqlite:///data/seismos.db
```

### Параметры обнаружения

Задаются в `DetectionParams`. Часть доступна через окружение (вложенные
поля разделяются двойным подчёркиванием), например:

```dotenv
SEISMOS_DETECTION__TRIGGER_RATIO=3.5
SEISMOS_DETECTION__CFAR_ALPHA=4.0
SEISMOS_DETECTION__BAND_LOW_HZ=5
SEISMOS_DETECTION__BAND_HIGH_HZ=120
```

## 5. Конфигурация объекта

Файл `config/site.yaml` описывает датчики, цепочки и зоны.

### Датчики

| Поле | Обязательное | Описание |
|---|---|---|
| `id` | да | Уникальный идентификатор |
| `name` | да | Название для оператора |
| `zone_id` | да | Зона охраны |
| `chain_index` | да | Позиция в цепочке (порядок опроса) |
| `position_m` | нет | Погонная координата на периметре |
| `kind` | нет | `gs20dx`, `gs20dx-array`, `vibro`, `contact` |
| `sample_rate` | нет | Частота дискретизации, Гц |

### Цепочки

| Поле | Описание |
|---|---|
| `id` | Идентификатор цепочки |
| `transport` | `sim`, `udp`, `tcp`, `spidev`, `file` |
| `sensors` | Список идентификаторов датчиков |
| `address` | `host:port` для сетевых транспортов |
| `sample_rate` | Частота дискретизации |

### Зоны

| Поле | Описание |
|---|---|
| `id` | Идентификатор зоны |
| `name` | Название |
| `kind` | `seismic`, `vibro`, `combined`, `gate` |
| `priority` | Приоритет (1 — низкий, 3 — высокий) |
| `length_m` | Протяжённость участка |

## 6. Управление доступом

Если задан `SEISMOS_AUTH_TOKEN`, все изменяющие операции (`arm`, `disarm`,
квитирование, вставка событий) требуют заголовок:

```
Authorization: Bearer <токен>
```

либо

```
X-API-Key: <токен>
```

Операции чтения остаются открытыми.

## 7. Хранение данных

- События, тревоги и аудит — в SQLite (`data/seismos.db`).
- Каталог `data/recordings/` — для записей сигналов (при использовании
  транспорта `file`).
- Очистка старых событий: параметр `SEISMOS_RETENTION_DAYS`.

## 8. Проверка установки

```bash
seismos version      # версия
seismos sensors      # конфигурация датчиков и зон
seismos selftest     # самопроверка конвейера обработки
pytest               # полный набор тестов (нужен экстрак dev)
```

## 9. Диагностика

| Проблема | Решение |
|---|---|
| `ModuleNotFoundError: seismos` | установите пакет (`pip install -e .`) или запускайте `python -m seismos.cli.main` |
| Порт занят | задайте другой `SEISMOS_PORT` |
| Консоль пуста | проверьте соединение WebSocket (`/ws`) в консоли браузера |
| Нет событий на стенде | убедитесь, что система на охране (`POST /api/v1/arm`) |
| Ложные срабатывания | поднимите `SEISMOS_DETECTION__CFAR_ALPHA` |
