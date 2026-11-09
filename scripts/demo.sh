#!/usr/bin/env bash
# Демонстрационный прогон СЕЙСМОС без оборудования.
# Запускает сервер, ставит систему на охрану, вбрасывает несколько
# воздействий и печатает активные тревоги.

set -euo pipefail

HOST="${SEISMOS_HOST:-127.0.0.1}"
PORT="${SEISMOS_PORT:-8000}"
BASE="http://${HOST}:${PORT}"

echo "== СЕЙСМОС: демонстрационный прогон =="

echo "-- Запуск сервера..."
python -m seismos.cli.main serve --host "${HOST}" --port "${PORT}" &
SERVER_PID=$!
trap 'kill "${SERVER_PID}" 2>/dev/null || true' EXIT

echo "-- Ожидание готовности..."
for _ in $(seq 1 30); do
  if curl -sf "${BASE}/health" >/dev/null 2>&1; then break; fi
  sleep 0.5
done

echo "-- Статус:"
curl -s "${BASE}/api/v1/status"; echo

echo "-- Постановка на охрану:"
curl -s -X POST "${BASE}/api/v1/arm"; echo

for cls in footstep group vehicle digging climb impact; do
  echo "-- Вбрасывание воздействия: ${cls}"
  curl -s -X POST "${BASE}/api/v1/simulate" \
    -H 'Content-Type: application/json' \
    -d "{\"sensor_id\":\"S01\",\"event_class\":\"${cls}\",\"duration_s\":3.0}" \
    | python -c "import sys,json; d=json.load(sys.stdin); print('   событий:', len(d['events']), [e['event_class'] for e in d['events']])"
done

echo "-- Активные тревоги:"
curl -s "${BASE}/api/v1/alarms/active" \
  | python -c "import sys,json; d=json.load(sys.stdin); print('   всего:', len(d)); [print('   -', a['zone_id'], a['event_class'], a['state']) for a in d]"

echo "== Готово. Консоль: ${BASE}/ =="
