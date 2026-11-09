# Справочник API СЕЙСМОС

Базовый адрес: `http://<host>:<port>`. Версионированный префикс REST —
`/api/v1`. Интерактивная документация — `/docs` (Swagger UI).

## Аутентификация

Если задан `SEISMOS_AUTH_TOKEN`, изменяющие запросы требуют токен в
заголовке:

```
Authorization: Bearer <токен>
```

или

```
X-API-Key: <токен>
```

Читающие запросы открыты. При неверном токене — `401`.

## Коды ответов

| Код | Значение |
|---|---|
| 200 | Успех |
| 401 | Неверный токен доступа |
| 404 | Объект не найден (датчик, зона, тревога) |
| 422 | Ошибка валидации тела запроса |
| 500 | Внутренняя ошибка |

---

## Системные

### `GET /health`

Проверка доступности сервиса.

```json
{"status": "ok", "version": "1.0.0", "ts": 1794218678.77}
```

### `GET /api/v1/status`

Сводное состояние системы.

```json
{
  "state": "armed",
  "sensors_total": 9,
  "sensors_online": 9,
  "zones_total": 4,
  "zones_armed": 4,
  "active_alarms": 0,
  "events_total": 12,
  "uptime_s": 3600.0,
  "version": "1.0.0",
  "started_at": 1794218673.2
}
```

`state` — одно из `disarmed`, `arming`, `armed`, `alarm`.

### `GET /api/v1/metrics`

Расширенные метрики: сводка по датчикам, статистика событий, число
подписчиков шины.

```json
{
  "sensors": {"sensors_total": 9, "sensors_online": 9, "zones_total": 4, "zones_armed": 4},
  "events": {"events_total": 12, "by_class": {"footstep": 5, "vehicle": 7}, "alarms_by_zone": {"Z1": 3}},
  "active_alarms": 0,
  "subscribers": 1,
  "state": "armed"
}
```

### `POST /api/v1/simulate`

Вставка синтетического воздействия (стенд/демонстрация). Требует токен,
если он задан.

Тело запроса:

```json
{"sensor_id": "S01", "event_class": "vehicle", "duration_s": 3.0}
```

Допустимые `event_class`: `footstep`, `group`, `vehicle`, `digging`,
`climb`, `impact`, `weather`.

Ответ:

```json
{
  "injected": 6548,
  "events": [
    {
      "id": "3fdabbdc7a10460e",
      "sensor_id": "S01",
      "zone_id": "Z1",
      "kind": "intrusion",
      "level": 3,
      "event_class": "vehicle",
      "confidence": 0.76,
      "ratio": 10.78,
      "peak": 38.24,
      "duration_s": 1.15,
      "dominant_hz": 11.27
    }
  ]
}
```

---

## Периметр

### `GET /api/v1/sensors`

Список датчиков (без сетевых адресов в публичном представлении).

```json
[
  {
    "id": "S01", "name": "Периметр 0 м", "zone_id": "Z1",
    "kind": "gs20dx", "chain_index": 0, "position_m": 0.0,
    "online": true, "last_seen": 1794218678.8
  }
]
```

### `GET /api/v1/sensors/{sensor_id}`

Один датчик по идентификатору. `404`, если не найден.

### `GET /api/v1/zones`

Список зон с числом датчиков и активных тревог.

```json
[
  {
    "id": "Z1", "name": "Северный участок", "kind": "seismic",
    "priority": 2, "length_m": 200, "armed": true,
    "sensor_count": 3, "active_alarms": 0
  }
]
```

### `GET /api/v1/zones/{zone_id}`

Одна зона по идентификатору. `404`, если не найдена.

---

## Управление

### `POST /api/v1/arm`

Поставить всю систему на охрану.

```json
{"state": "armed"}
```

### `POST /api/v1/disarm`

Снять систему с охраны.

```json
{"state": "disarmed"}
```

### `POST /api/v1/zones/{zone_id}/arm`

Управление отдельной зоной.

Тело:

```json
{"armed": true}
```

Ответ:

```json
{"zone_id": "Z1", "armed": true}
```

---

## События

### `GET /api/v1/events`

Журнал событий из базы с фильтрацией.

Параметры запроса:

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `zone_id` | строка | — | Фильтр по зоне |
| `since` | число | — | Начало периода (unix-время) |
| `until` | число | — | Конец периода |
| `min_level` | 0…3 | 0 | Минимальный уровень |
| `limit` | 1…5000 | 200 | Размер страницы |
| `offset` | ≥ 0 | 0 | Смещение |

### `GET /api/v1/events/recent`

Последние события из оперативного кольцевого буфера (быстро, без БД).

Параметр `limit` (1…500, по умолчанию 50).

Элемент события:

```json
{
  "id": "396834fae00b4d46",
  "ts": 1794218724.77,
  "sensor_id": "S01",
  "zone_id": "Z1",
  "kind": "warning",
  "level": 1,
  "event_class": "footstep",
  "confidence": 0.93,
  "ratio": 4.93,
  "peak": 4.01,
  "duration_s": 3.14,
  "dominant_hz": 25.84,
  "meta": {"rms": 0.72, "centroid_hz": 33.11, "zcr": 0.021}
}
```

---

## Тревоги

### `GET /api/v1/alarms`

Журнал тревог.

| Параметр | Описание |
|---|---|
| `state` | `active`, `acknowledged`, `reset` |
| `zone_id` | Фильтр по зоне |
| `limit` | Размер страницы (по умолчанию 200) |

### `GET /api/v1/alarms/active`

Только активные тревоги.

```json
[
  {
    "id": "e5dc59bb22d14113",
    "ts": 1794218678.85,
    "sensor_id": "S01",
    "zone_id": "Z1",
    "level": 3,
    "event_class": "vehicle",
    "confidence": 0.76,
    "state": "active",
    "ack_ts": null,
    "ack_by": null,
    "comment": "",
    "event_ids": ["3fdabbdc7a10460e"]
  }
]
```

### `POST /api/v1/alarms/{alarm_id}/ack`

Квитировать тревогу.

Тело:

```json
{"comment": "Проверено, ложное срабатывание"}
```

Ответ — обновлённая тревога со `state: "acknowledged"`. `404`, если тревога
не найдена.

### `POST /api/v1/alarms/{alarm_id}/reset`

Сбросить тревогу (`state: "reset"`).

---

## WebSocket

### `GET /ws` (WebSocket)

Поток событий в реальном времени. Сразу после подключения сервер присылает
приветствие:

```json
{"topic": "hello", "payload": {"version": "1.0.0", "state": "armed"}}
```

Далее поступают сообщения вида `{"topic": ..., "payload": ...}`.

| `topic` | Когда приходит | Содержимое `payload` |
|---|---|---|
| `event` | Новое событие обнаружения | Событие (как в `/events/recent`) |
| `alarm` | Сформирована новая тревога | Тревога |
| `alarm_update` | Тревога квитирована/сброшена | Тревога |
| `state` | Изменение режима охраны | `{"state": "...", "ts": ...}` |
| `zone` | Изменение режима зоны | `{"zone_id": "...", "armed": true}` |

Пример клиента (JavaScript):

```js
const ws = new WebSocket(`ws://${location.host}/ws`);
ws.onmessage = (m) => {
  const { topic, payload } = JSON.parse(m.data);
  if (topic === "event") console.log("событие:", payload);
  if (topic === "alarm") console.log("тревога:", payload);
};
```

---

## Примеры

### Поставить на охрану и вбросить воздействие

```bash
curl -X POST http://localhost:8000/api/v1/arm
curl -X POST http://localhost:8000/api/v1/simulate \
  -H 'Content-Type: application/json' \
  -d '{"sensor_id": "S01", "event_class": "vehicle", "duration_s": 3.0}'
curl http://localhost:8000/api/v1/alarms/active
```

### Квитировать тревогу

```bash
curl -X POST http://localhost:8000/api/v1/alarms/<id>/ack \
  -H 'Content-Type: application/json' \
  -d '{"comment": "Осмотрено"}'
```

### Выборка событий за период

```bash
curl "http://localhost:8000/api/v1/events?min_level=2&limit=50"
```
