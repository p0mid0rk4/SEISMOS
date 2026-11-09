/* Консоль оператора СЕЙСМОС — клиентская логика. */

const API = "";
const state = {
  zones: [],
  sensors: [],
  alarms: [],
  events: [],
  status: null,
  liveBuffer: [],
  liveSensor: null,
};

const LEVEL_LABEL = { 0: "шум", 1: "предупреждение", 2: "тревога", 3: "проникновение" };
const CLASS_LABEL = {
  none: "—", footstep: "шаги", group: "группа", vehicle: "техника",
  digging: "подкоп", climb: "перелаз", impact: "удар", tamper: "вскрытие",
  weather: "метео", unknown: "неизвестно",
};

function fmtTime(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString("ru-RU", { hour12: false });
}
function fmtDate(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleString("ru-RU", { hour12: false });
}

async function api(path, options = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

function setStateBadge(s) {
  const el = document.getElementById("state-badge");
  el.dataset.state = s;
  el.textContent = {
    armed: "НА ОХРАНЕ", disarmed: "СНЯТО С ОХРАНЫ",
    arming: "ПОСТАНОВКА…", alarm: "ТРЕВОГА",
  }[s] || s.toUpperCase();
}

function renderMetrics() {
  const s = state.status || {};
  const items = [
    { label: "Датчиков на связи", value: `${s.sensors_online ?? 0}/${s.sensors_total ?? 0}`, cls: "ok" },
    { label: "Зон на охране", value: `${s.zones_armed ?? 0}/${s.zones_total ?? 0}`, cls: "" },
    { label: "Активных тревог", value: s.active_alarms ?? 0, cls: (s.active_alarms ? "danger" : "") },
    { label: "Событий в сеансе", value: s.events_total ?? 0, cls: "" },
  ];
  document.getElementById("metrics").innerHTML = items.map((i) =>
    `<div class="metric ${i.cls}"><div class="value">${i.value}</div><div class="label">${i.label}</div></div>`
  ).join("");
}

function renderPerimeter() {
  const map = document.getElementById("perimeter-map");
  const zones = state.zones;
  const total = zones.reduce((acc, z) => acc + (z.length_m || 100), 0) || 1;
  let left = 0;
  const segs = zones.map((z) => {
    const width = ((z.length_m || 100) / total) * 100;
    const seg = `<div class="segment ${zoneClass(z)}" style="left:${left}%;width:calc(${width}% - 6px)" title="${z.name}">
        <span>${z.name}</span></div>`;
    left += width;
    return seg;
  }).join("");

  const pins = state.sensors.map((s) => {
    const pos = (s.position_m / (state.status?.perimeter_length_m || 640)) * 100;
    const online = s.online ? "online" : "";
    return `<div class="sensor-pin ${online}" style="left:${Math.min(99, pos)}%" title="${s.name}"></div>`;
  }).join("");

  map.innerHTML = `<div class="perimeter-line">${segs}${pins}</div>`;
}

function zoneClass(z) {
  if (z.active_alarms > 0) return "alarm";
  if (!z.armed) return "";
  return "ok";
}

function renderZones() {
  const el = document.getElementById("zone-list");
  if (!state.zones.length) { el.innerHTML = '<div class="empty">Зоны не заданы</div>'; return; }
  el.innerHTML = state.zones.map((z) => `
    <div class="zone-card">
      <div class="title">
        <strong>${z.name}</strong>
        <span class="switch ${z.armed ? "on" : ""}" data-zone="${z.id}" data-armed="${z.armed}">
          ${z.armed ? "охрана" : "выкл"}
        </span>
      </div>
      <div class="sub">${z.id} · тип: ${z.kind} · датчиков: ${z.sensor_count} · приоритет ${z.priority}</div>
    </div>`).join("");

  el.querySelectorAll(".switch").forEach((sw) => {
    sw.addEventListener("click", async () => {
      const zoneId = sw.dataset.zone;
      const armed = sw.dataset.armed !== "true";
      await api(`/api/v1/zones/${zoneId}/arm`, {
        method: "POST", body: JSON.stringify({ armed }),
      });
      await refreshZones();
    });
  });
}

function renderAlarms() {
  const el = document.getElementById("alarm-list");
  document.getElementById("alarm-counter").textContent = state.alarms.length;
  if (!state.alarms.length) { el.innerHTML = '<li class="empty">Активных тревог нет</li>'; return; }
  el.innerHTML = state.alarms.map((a) => `
    <li class="alarm-item">
      <div>
        <div class="cls">${CLASS_LABEL[a.event_class] || a.event_class}</div>
        <div class="meta">${fmtDate(a.ts)} · зона ${a.zone_id} · датчик ${a.sensor_id}
          · уверенность ${(a.confidence * 100).toFixed(0)}%</div>
      </div>
      <button class="btn" data-alarm="${a.id}">Принять</button>
    </li>`).join("");

  el.querySelectorAll("button[data-alarm]").forEach((b) => {
    b.addEventListener("click", async () => {
      await api(`/api/v1/alarms/${b.dataset.alarm}/ack`, {
        method: "POST", body: JSON.stringify({ comment: "принято оператором" }),
      });
      await refreshAlarms();
    });
  });
}

function renderEvents() {
  const minLevel = parseInt(document.getElementById("event-filter").value, 10);
  const rows = state.events.filter((e) => e.level >= minLevel).slice(0, 200);
  const tbody = document.getElementById("event-rows");
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty">Событий нет</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map((e) => `
    <tr class="lvl-${e.level}">
      <td>${fmtTime(e.ts)}</td>
      <td>${e.zone_id}</td>
      <td>${e.sensor_id}</td>
      <td>${CLASS_LABEL[e.event_class] || e.event_class}</td>
      <td>${(e.confidence * 100).toFixed(0)}%</td>
      <td>${(e.ratio || 0).toFixed(1)}</td>
      <td><span class="badge lvl-${e.level}">${LEVEL_LABEL[e.level] || e.level}</span></td>
    </tr>`).join("");
}

function drawLive() {
  const canvas = document.getElementById("live-canvas");
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = "#1a2636";
  ctx.lineWidth = 1;
  for (let i = 1; i < 4; i++) {
    ctx.beginPath(); ctx.moveTo(0, (h / 4) * i); ctx.lineTo(w, (h / 4) * i); ctx.stroke();
  }
  const data = state.liveBuffer;
  if (data.length < 2) return;
  const max = Math.max(1, ...data.map(Math.abs));
  ctx.strokeStyle = "#35d0ba";
  ctx.lineWidth = 1.4;
  ctx.beginPath();
  data.forEach((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h / 2 - (v / max) * (h / 2 - 8);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

async function refreshStatus() {
  state.status = await api("/api/v1/status");
  setStateBadge(state.status.state);
  renderMetrics();
}

async function refreshZones() {
  state.zones = await api("/api/v1/zones");
  renderZones();
  renderPerimeter();
}

async function refreshSensors() {
  state.sensors = await api("/api/v1/sensors");
  renderPerimeter();
}

async function refreshAlarms() {
  state.alarms = await api("/api/v1/alarms/active");
  renderAlarms();
}

async function refreshEvents() {
  state.events = await api("/api/v1/events/recent?limit=200");
  renderEvents();
}

function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  const conn = document.getElementById("conn-status");
  ws.onopen = () => { conn.textContent = "соединение установлено"; conn.className = "conn online"; };
  ws.onclose = () => {
    conn.textContent = "соединение потеряно, переподключение…";
    conn.className = "conn offline";
    setTimeout(connectWS, 3000);
  };
  ws.onmessage = (msg) => {
    const { topic, payload } = JSON.parse(msg.data);
    if (topic === "event") {
      state.events.unshift(payload);
      state.events = state.events.slice(0, 500);
      renderEvents();
      if (payload.sensor_id === state.liveSensor) {
        state.liveBuffer.push(payload.peak || 0);
        if (state.liveBuffer.length > 240) state.liveBuffer.shift();
        drawLive();
      }
      refreshStatus();
    } else if (topic === "alarm") {
      state.alarms.unshift(payload);
      renderAlarms();
      renderPerimeter();
      refreshStatus();
    } else if (topic === "alarm_update") {
      refreshAlarms();
      refreshStatus();
    } else if (topic === "state") {
      setStateBadge(payload.state);
      refreshStatus();
    }
  };
}

function bindControls() {
  document.getElementById("btn-arm").addEventListener("click", async () => {
    await api("/api/v1/arm", { method: "POST" });
    await refreshStatus();
  });
  document.getElementById("btn-disarm").addEventListener("click", async () => {
    await api("/api/v1/disarm", { method: "POST" });
    await refreshStatus();
  });
  document.getElementById("btn-sim").addEventListener("click", async () => {
    const sensor = state.sensors[Math.floor(Math.random() * state.sensors.length)];
    if (!sensor) return;
    const classes = ["footstep", "group", "vehicle", "digging", "climb"];
    const cls = classes[Math.floor(Math.random() * classes.length)];
    await api("/api/v1/simulate", {
      method: "POST",
      body: JSON.stringify({ sensor_id: sensor.id, event_class: cls, duration_s: 3.0 }),
    });
    await refreshEvents();
  });
  document.getElementById("event-filter").addEventListener("change", renderEvents);
}

function tickClock() {
  document.getElementById("clock").textContent = new Date().toLocaleTimeString("ru-RU", { hour12: false });
}

async function init() {
  bindControls();
  tickClock();
  setInterval(tickClock, 1000);
  await refreshStatus();
  await refreshZones();
  await refreshSensors();
  await refreshAlarms();
  await refreshEvents();
  state.liveSensor = state.sensors[0]?.id || null;
  document.getElementById("live-sensor").textContent = state.liveSensor || "—";
  connectWS();
  setInterval(refreshStatus, 5000);
  setInterval(refreshZones, 10000);
}

init().catch((err) => console.error(err));
