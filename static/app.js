/* Panel de rutas - frontend vanilla + Leaflet */

const REFRESH_MS = 10000;
const DEFAULT_CENTER = [-4.6097, -74.0817]; // Bogota

let map;
let markers = {};
let lines = {};
let selected = null;
let state = null;
let fitDone = false;

const $ = (sel) => document.querySelector(sel);

// ------------------------------------------------------------------ mapa
function initMap() {
  map = L.map("map", { zoomControl: true, preferCanvas: true }).setView(DEFAULT_CENTER, 12);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(map);
}

function markerIcon(rep) {
  const letter = (rep.name || rep.username).trim().charAt(0).toUpperCase();
  return L.divIcon({
    className: "",
    html: `<div class="rep-marker" style="width:26px;height:26px;background:${rep.color}">${letter}</div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });
}

function draw(data) {
  const seen = new Set();

  data.reps.forEach((rep) => {
    if (!rep.last) return;
    seen.add(rep.username);

    const pos = [rep.last.lat, rep.last.lon];

    if (!markers[rep.username]) {
      markers[rep.username] = L.marker(pos, { icon: markerIcon(rep) })
        .addTo(map)
        .on("click", () => select(rep.username));
    } else {
      markers[rep.username].setLatLng(pos);
      markers[rep.username].setIcon(markerIcon(rep));
    }
    markers[rep.username].bindTooltip(rep.name, {
      permanent: true, direction: "right", offset: [16, 0], className: "rep-label",
    });

    const track = data.tracks[rep.username] || [];
    const isSel = selected === rep.username;
    const style = {
      color: rep.color,
      weight: isSel ? 5 : 3,
      opacity: isSel || !selected ? 0.95 : 0.35,
    };

    if (!lines[rep.username]) {
      lines[rep.username] = L.polyline(track, style).addTo(map);
    } else {
      lines[rep.username].setLatLngs(track);
      lines[rep.username].setStyle(style);
    }
  });

  // limpiar los que ya no existen
  Object.keys(markers).forEach((u) => {
    if (!seen.has(u)) { map.removeLayer(markers[u]); delete markers[u]; }
  });
  Object.keys(lines).forEach((u) => {
    if (!seen.has(u)) { map.removeLayer(lines[u]); delete lines[u]; }
  });

  if (!fitDone && seen.size) {
    const pts = Object.values(markers).map((m) => m.getLatLng());
    if (pts.length === 1) map.setView(pts[0], 15);
    else map.fitBounds(L.latLngBounds(pts).pad(0.25));
    fitDone = true;
  }
}

function select(username) {
  selected = selected === username ? null : username;
  document.querySelectorAll(".rep").forEach((el) => {
    el.classList.toggle("active", el.dataset.user === selected);
  });
  if (state) draw(state);
  if (selected && markers[selected]) map.panTo(markers[selected].getLatLng());
}

// --------------------------------------------------------------- sidebar
function ago(ts) {
  if (!ts) return "sin datos";
  const diff = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (diff < 60) return "ahora";
  if (diff < 3600) return `hace ${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `hace ${Math.floor(diff / 3600)} h`;
  return `hace ${Math.floor(diff / 86400)} d`;
}

function renderList(data) {
  const list = $("#repList");
  $("#repCount").textContent = `${data.reps.length} repartidor${data.reps.length === 1 ? "" : "es"}`;
  list.innerHTML = "";

  if (!data.reps.length) {
    list.innerHTML = `<p class="hint">Aún no hay repartidores. Crea uno con “+ Repartidor”
      y configura la app en su celular.</p>`;
    return;
  }

  data.reps
    .slice()
    .sort((a, b) => (b.last?.tst || 0) - (a.last?.tst || 0))
    .forEach((rep) => {
      const el = document.createElement("div");
      el.className = "rep" + (selected === rep.username ? " active" : "");
      el.dataset.user = rep.username;
      el.style.borderLeftColor = rep.color;

      const batt = rep.last?.batt != null ? `${rep.last.batt}%` : "—";
      el.innerHTML = `
        <div class="rep-top">
          <div>
            <div class="rep-name">${esc(rep.name)}</div>
            <div class="rep-user">@${esc(rep.username)}</div>
          </div>
          <span class="pill ${rep.online ? "on" : ""}">${rep.online ? "EN VIVO" : esc(ago(rep.last?.tst))}</span>
        </div>
        <div class="rep-meta">
          <span><b>${rep.km}</b> km hoy</span>
          <span><b>${rep.points}</b> puntos</span>
          <span>batería <b>${batt}</b></span>
        </div>
        <div class="rep-actions">
          <button class="ghost" data-cfg="${esc(rep.username)}">Configurar app</button>
          <button class="ghost" data-del="${esc(rep.username)}">Eliminar</button>
        </div>`;

      el.addEventListener("click", (ev) => {
        if (ev.target.closest("button")) return;
        select(rep.username);
      });
      list.appendChild(el);
    });

  list.querySelectorAll("[data-cfg]").forEach((b) =>
    b.addEventListener("click", () => openConfig(b.dataset.cfg))
  );
  list.querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", () => removeRep(b.dataset.del))
  );
}

function esc(t) {
  return String(t ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

// ----------------------------------------------------------------- datos
async function refresh() {
  const day = $("#datePicker").value;
  try {
    const res = await fetch(`/api/state?date=${encodeURIComponent(day)}`);
    if (!res.ok) throw new Error(res.status);
    state = await res.json();
    renderList(state);
    draw(state);
  } catch (err) {
    console.error("Error al actualizar:", err);
  }
}

// ---------------------------------------------------------------- modales
function openConfig(username) {
  const rep = state?.reps.find((r) => r.username === username);
  if (!rep) return;
  $("#cfgName").textContent = rep.name;
  $("#cfgHost").textContent = state.host;
  $("#cfgUser").textContent = rep.username;
  $("#cfgPass").textContent = "volantes2026";
  $("#cfgTid").textContent = rep.username.slice(0, 2).toUpperCase();
  $("#modalConfig").hidden = false;
}

function openAdd() {
  $("#newName").value = "";
  $("#newPhone").value = "";
  $("#modalAdd").hidden = false;
  $("#newName").focus();
}

async function createRep() {
  const name = $("#newName").value.trim();
  if (!name) return;
  const res = await fetch("/api/reps", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, phone: $("#newPhone").value.trim() }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.error || "No se pudo crear el repartidor");
    return;
  }
  const rep = await res.json();
  $("#modalAdd").hidden = true;
  await refresh();
  openConfig(rep.username);
}

async function removeRep(username) {
  if (!confirm(`¿Eliminar a @${username} y todo su historial?`)) return;
  await fetch(`/api/reps/${encodeURIComponent(username)}`, { method: "DELETE" });
  if (selected === username) selected = null;
  await refresh();
}

// -------------------------------------------------------------- arranque
function setupUi() {
  const today = new Date();
  const iso = new Date(today.getTime() - today.getTimezoneOffset() * 60000)
    .toISOString().slice(0, 10);
  $("#datePicker").value = iso;
  $("#datePicker").addEventListener("change", refresh);

  $("#btnAdd").addEventListener("click", openAdd);
  $("#btnCreate").addEventListener("click", createRep);
  $("#newName").addEventListener("keydown", (e) => { if (e.key === "Enter") createRep(); });

  $("#btnAll").addEventListener("click", () => { selected = null; if (state) { renderList(state); draw(state); } });

  document.querySelectorAll("[data-close]").forEach((b) =>
    b.addEventListener("click", () => { b.closest(".modal").hidden = true; })
  );
  document.querySelectorAll(".modal").forEach((m) =>
    m.addEventListener("click", (e) => { if (e.target === m) m.hidden = true; })
  );
  document.querySelectorAll("[data-copy]").forEach((b) =>
    b.addEventListener("click", () => {
      const txt = document.getElementById(b.dataset.copy).textContent;
      navigator.clipboard?.writeText(txt);
      b.textContent = "copiado";
      setTimeout(() => (b.textContent = "copiar"), 1200);
    })
  );
}

initMap();
setupUi();
refresh();
setInterval(refresh, REFRESH_MS);
