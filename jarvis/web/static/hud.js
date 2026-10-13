// Jarvis HUD client. Plain JS, no build step.
"use strict";

const $ = (id) => document.getElementById(id);
const MONTHS = ["Januar", "Februar", "Mart", "April", "Maj", "Jun", "Jul", "Avgust", "Septembar", "Oktobar", "Novembar", "Decembar"];
const WEEKDAYS = ["Nedelja", "Ponedeljak", "Utorak", "Sreda", "Četvrtak", "Petak", "Subota"];
const SHORT_DAYS = ["ned", "pon", "uto", "sre", "čet", "pet", "sub"];
const CLIENT_ID = Math.random().toString(36).slice(2);

let TOKEN = "";
let state = null;
let busy = false;
let transcriptLoaded = false;

// ------------------------------------------------------------- token -----
function initToken() {
  const url = new URL(location.href);
  const t = url.searchParams.get("t");
  if (t) {
    try { localStorage.setItem("jarvis_token", t); } catch (_) { /* private mode */ }
    url.searchParams.delete("t");
    history.replaceState(null, "", url.pathname + url.search);
    TOKEN = t;
  } else {
    try { TOKEN = localStorage.getItem("jarvis_token") || ""; } catch (_) { TOKEN = ""; }
  }
}

async function api(path, opts = {}) {
  const headers = Object.assign({ "X-Jarvis-Token": TOKEN }, opts.headers || {});
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.json);
  }
  const res = await fetch(path, Object.assign({}, opts, { headers }));
  if (res.status === 401) { showTokenPrompt(); throw new Error("unauthorized"); }
  return res;
}

function showTokenPrompt() { $("tokenOverlay").classList.remove("hidden"); }

// ------------------------------------------------------------- helpers ---
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}

function setArc(id, fraction, circumference) {
  const f = Math.max(0, Math.min(1, fraction || 0));
  $(id).setAttribute("stroke-dashoffset", String(circumference * (1 - f)));
}

let toastTimer = null;
function toast(title, text) {
  const t = $("toast");
  t.replaceChildren(el("b", null, title), document.createTextNode(text || ""));
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 5000);
}

function hhmm(iso) {
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleTimeString("sr-Latn-RS", { hour: "2-digit", minute: "2-digit" });
}

// ------------------------------------------------------- clock & dates ---
function renderDays() {
  const now = new Date();
  const days = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  const box = $("days");
  box.replaceChildren();
  for (let d = 1; d <= days; d++) {
    const s = el("span", null, String(d).padStart(2, "0"));
    const wd = new Date(now.getFullYear(), now.getMonth(), d).getDay();
    if (wd === 0 || wd === 6) s.classList.add("we");
    if (d === now.getDate()) s.classList.add("today");
    box.appendChild(s);
  }
  const today = box.querySelector(".today");
  if (today) today.scrollIntoView({ inline: "center", block: "nearest" });
  $("month").textContent = MONTHS[now.getMonth()];
  $("dayNum").textContent = String(now.getDate());
  $("weekday").textContent = WEEKDAYS[now.getDay()];
  setArc("dateArc", now.getDate() / days, 553);
}

function tick() {
  const now = new Date();
  $("clock").textContent = now.toLocaleTimeString("sr-Latn-RS", { hour: "2-digit", minute: "2-digit" });
  setArc("secArc", now.getSeconds() / 60, 553);
  if (now.getHours() === 0 && now.getMinutes() === 0 && now.getSeconds() === 0) renderDays();
}

// ------------------------------------------------------------- state -----
async function loadState() {
  const res = await api("/api/state");
  state = await res.json();
  renderAll();
}

function renderAll() {
  if (!state) return;
  $("cityName").textContent = state.city;
  $("wxCity").textContent = state.city;
  renderStatus();
  renderTasks(state.tasks);
  renderReminders(state.reminders);
  renderFeed(state.feed);
  renderApprovals(state.pending);
  if (!transcriptLoaded) { renderTranscript(state.history); transcriptLoaded = true; }
  renderPairing(state.pairing_code);
}

function renderStatus() {
  $("btnStop").classList.toggle("on", state.paused);
  $("btnStop").textContent = state.paused ? "Pauzirano" : "Stop";
  $("btnDnd").classList.toggle("on", state.dnd);
  document.querySelectorAll("[data-mode]").forEach((b) => b.classList.toggle("on", b.dataset.mode === state.voice_mode));
  const g = state.google || {};
  $("btnGoogle").classList.toggle("hidden", !(g.configured && !g.connected));

  const ch = $("channels");
  ch.replaceChildren(...state.channels.filter((c) => c.name !== "test").map((c) => el("span", "chip static on", c.label)));
  if (state.quiet) ch.appendChild(el("span", "chip static", "Tihi sati"));
  ch.appendChild(el("span", "chip static", "LLM: " + state.llm));

  const bat = state.battery && typeof state.battery.percentage === "number" ? state.battery.percentage : null;
  $("vBattery").textContent = bat === null ? "–" : bat + "%";
  setArc("gBattery", bat === null ? 0 : bat / 100, 264);
  const pending = (state.pending || []).length;
  $("vPending").textContent = String(pending);
  setArc("gPending", pending / 5, 264);
  const tasks = (state.tasks || []).length;
  $("vTasks").textContent = String(tasks);
  setArc("gTasks", tasks / 10, 264);
}

function renderTasks(tasks) {
  const ul = $("tasks");
  ul.replaceChildren();
  $("taskCount").textContent = tasks.length ? String(tasks.length) : "";
  if (!tasks.length) { ul.appendChild(el("li", "empty", "Nema otvorenih zadataka.")); return; }
  const now = new Date();
  for (const t of tasks) {
    const li = el("li");
    const box = el("button", "check");
    box.title = "Gotovo";
    box.setAttribute("aria-label", "Označi kao gotovo: " + t.title);
    box.onclick = () => sendText(`/gotovo ${t.id}`, true);
    const main = el("span", "grow" + (t.priority === 1 ? " prio1" : ""), t.title);
    if (t.due_at) {
      const due = new Date(t.due_at);
      const late = due < now;
      const sub = el("span", "sub", (late ? "⚠ kasni · " : "rok ") + due.toLocaleString("sr-Latn-RS", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }));
      if (late) sub.style.color = "var(--red)";
      main.appendChild(sub);
    }
    li.append(box, main);
    ul.appendChild(li);
  }
}

function renderReminders(rs) {
  const ul = $("reminders");
  ul.replaceChildren();
  if (!rs.length) { ul.appendChild(el("li", "empty", "Nema podsetnika.")); return; }
  for (const r of rs) {
    const d = new Date(r.at);
    const li = el("li");
    li.append(el("span", "when", d.toLocaleDateString("sr-Latn-RS", { day: "2-digit", month: "2-digit" }) + " " + hhmm(r.at)), el("span", "grow", r.text));
    ul.appendChild(li);
  }
}

function feedItem(n) {
  const li = el("li", (n.urgent ? "urgent " : "") + (n.held || n.delivered === 0 ? "held" : ""));
  const main = el("span", "grow", n.title);
  if (n.text) main.appendChild(el("span", "sub", n.text.length > 280 ? n.text.slice(0, 280) + "…" : n.text));
  li.append(el("span", "when", hhmm(n.created_at)), main);
  return li;
}

function renderFeed(items) {
  const ul = $("feed");
  ul.replaceChildren(...items.map(feedItem));
  if (!items.length) ul.appendChild(el("li", "empty", "Tišina. Ništa novo."));
}

function renderPairing(code) {
  $("pairingPanel").classList.toggle("hidden", !code);
  $("pairingCode").textContent = code || "";
}

// ---------------------------------------------------------- approvals ----
function renderApprovals(actions) {
  const box = $("approvals");
  box.replaceChildren(...actions.map(approvalCard));
}

function approvalCard(a) {
  const card = el("div", "card");
  card.dataset.id = a.id;
  const head = el("div");
  head.append(el("span", "who", a.kind === "call" ? "📞 " + a.recipient_name : a.recipient_name), el("span", "via", a.channel_label + (a.recipient !== a.recipient_name ? " · " + a.recipient : "")));
  card.appendChild(head);
  const p = a.payload || {};
  if (p.in_reply_to) card.appendChild(el("div", "ctx", "↩ " + (p.summary || p.in_reply_to.slice(0, 160))));
  if (p.reason === "missed_call") card.appendChild(el("div", "ctx", "↩ propušten poziv"));
  if (p.subject) card.appendChild(el("div", "ctx", "Naslov: " + p.subject));
  const text = el("div", "text", a.kind === "call" ? "Da pozovem?" : a.payload.text);
  card.appendChild(text);

  const row = el("div", "row");
  const send = el("button", "btn green", a.kind === "call" ? "✓ Pozovi" : "✓ Pošalji");
  const edit = el("button", "btn", "✎ Izmeni");
  const reject = el("button", "btn red", "✕ Odbij");
  send.onclick = () => decide(a.id, "send", card);
  reject.onclick = () => decide(a.id, "reject", card);
  edit.onclick = () => {
    const ta = el("textarea");
    ta.value = a.payload.text;
    text.replaceWith(ta);
    edit.textContent = "Sačuvaj";
    edit.onclick = async () => {
      const r = await decide(a.id, "edit", card, ta.value);
      if (r && r.ok) { a.payload = r.action.payload; card.replaceWith(approvalCard(r.action)); }
    };
    ta.focus();
  };
  if (a.kind === "call") edit.classList.add("hidden");
  row.append(send, edit, reject);
  card.appendChild(row);
  return card;
}

async function decide(id, op, card, text) {
  card.querySelectorAll("button").forEach((b) => (b.disabled = true));
  try {
    const res = await api(`/api/actions/${id}/${op}`, { method: "POST", json: text !== undefined ? { text } : {} });
    const r = await res.json();
    toast(r.ok ? "Jarvis" : "Pažnja", r.message);
    if (op !== "edit" && r.ok) card.remove();
    return r;
  } catch (e) {
    toast("Greška", String(e.message || e));
  } finally {
    card.querySelectorAll("button").forEach((b) => (b.disabled = false));
  }
}

function upsertAction(a) {
  const box = $("approvals");
  const existing = box.querySelector(`.card[data-id="${a.id}"]`);
  if (a.status !== "pending") { if (existing) existing.remove(); return; }
  const card = approvalCard(a);
  if (existing) existing.replaceWith(card); else box.prepend(card);
}

// -------------------------------------------------------- conversation ---
function addMessage(role, text) {
  const t = $("transcript");
  t.appendChild(el("div", "msg " + role, text));
  t.scrollTop = t.scrollHeight;
}

function renderTranscript(history) {
  $("transcript").replaceChildren();
  if (!history.length) addMessage("system", `Spreman sam, ${state.owner}. Dodirni reaktor i pričaj, ili piši.`);
  for (const m of history) addMessage(m.role, m.content);
}

function setReactor(mode, label) {
  const r = $("reactor");
  r.classList.remove("listening", "thinking", "speaking");
  if (mode) r.classList.add(mode);
  $("reactorStatus").textContent = label || "Dodirni i pričaj";
}

async function sendText(text, quiet) {
  text = text.trim();
  if (!text || busy) return;
  busy = true;
  if (!quiet) addMessage("user", text);
  setReactor("thinking", "Razmišljam…");
  try {
    const res = await api("/api/chat", { method: "POST", json: { text, client_id: CLIENT_ID } });
    const data = await res.json();
    if (data.reply) addMessage("assistant", data.reply);
    if (data.reply && (data.voice_mode === "glas" || data.voice_mode === "oba")) await speak(data.reply);
    loadState().catch(() => {});
  } catch (e) {
    addMessage("system", "Ne mogu da dobijem Jarvisa: " + (e.message || e));
  } finally {
    busy = false;
    setReactor(null);
  }
}

let currentAudio = null;
async function speak(text) {
  try {
    const res = await api("/api/tts", { method: "POST", json: { text } });
    if (!res.ok) throw new Error("tts");
    const url = URL.createObjectURL(await res.blob());
    if (currentAudio) currentAudio.pause();
    currentAudio = new Audio(url);
    setReactor("speaking", "Govorim…");
    await new Promise((resolve) => {
      currentAudio.onended = resolve;
      currentAudio.onerror = resolve;
      currentAudio.play().catch(resolve);
    });
    URL.revokeObjectURL(url);
  } catch (_) {
    // Fallback: the browser's own voice (may not have Serbian).
    if ("speechSynthesis" in window) {
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "sr-RS";
      setReactor("speaking", "Govorim…");
      await new Promise((resolve) => { u.onend = resolve; u.onerror = resolve; speechSynthesis.speak(u); });
    }
  }
}

// --------------------------------------------------------------- voice ---
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let recorder = null;

function listen() {
  if (busy) return;
  if (currentAudio && !currentAudio.paused) { currentAudio.pause(); setReactor(null); return; }
  if (SR) return listenBrowser();
  return listenRecorder();
}

function listenBrowser() {
  if (recognition) { recognition.stop(); return; }
  recognition = new SR();
  recognition.lang = "sr-RS";
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;
  let finalText = "";
  setReactor("listening", "Slušam…");
  recognition.onresult = (ev) => {
    let interim = "";
    for (let i = ev.resultIndex; i < ev.results.length; i++) {
      const r = ev.results[i];
      if (r.isFinal) finalText += r[0].transcript; else interim += r[0].transcript;
    }
    $("reactorStatus").textContent = (finalText + interim).slice(-40) || "Slušam…";
  };
  recognition.onerror = (ev) => {
    recognition = null;
    setReactor(null);
    if (ev.error === "not-allowed") toast("Mikrofon", "Dozvoli mikrofon u pregledaču.");
    else if (ev.error !== "no-speech" && ev.error !== "aborted") listenRecorder();
  };
  recognition.onend = () => {
    recognition = null;
    setReactor(null);
    if (finalText.trim()) sendText(finalText);
  };
  recognition.start();
}

async function listenRecorder() {
  if (recorder && recorder.state === "recording") { recorder.stop(); return; }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (_) {
    toast("Mikrofon", "Nema pristupa mikrofonu.");
    return;
  }
  const chunks = [];
  recorder = new MediaRecorder(stream);
  recorder.ondataavailable = (e) => chunks.push(e.data);
  recorder.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    setReactor("thinking", "Prepoznajem…");
    const form = new FormData();
    form.append("audio", new Blob(chunks, { type: recorder.mimeType }), "voice.webm");
    try {
      const res = await api("/api/stt", { method: "POST", body: form });
      const data = await res.json();
      setReactor(null);
      if (data.text) sendText(data.text);
      else toast("Glas", data.error || "Nisam razumeo.");
    } catch (e) {
      setReactor(null);
      toast("Glas", String(e.message || e));
    }
  };
  recorder.start();
  setReactor("listening", "Snimam… dodirni za kraj");
  setTimeout(() => recorder && recorder.state === "recording" && recorder.stop(), 20000);
}

// ------------------------------------------------------ weather & cal ----
const ICONS = {
  sun: '<circle cx="24" cy="24" r="8"/><path d="M24 4v6M24 38v6M4 24h6M38 24h6M10 10l4 4M34 34l4 4M38 10l-4 4M14 34l-4 4"/>',
  cloud: '<path d="M14 36h20a8 8 0 0 0 0-16 11 11 0 0 0-21-2 8 8 0 0 0 1 18z"/>',
  part: '<circle cx="17" cy="17" r="6"/><path d="M17 5v3M5 17h3M9 9l2 2M25 9l-2 2"/><path d="M18 38h17a7 7 0 0 0 0-14 9 9 0 0 0-17 1 6.5 6.5 0 0 0 0 13z"/>',
  rain: '<path d="M14 30h20a8 8 0 0 0 0-16 11 11 0 0 0-21-2 8 8 0 0 0 1 18z"/><path d="M16 36l-2 6M24 36l-2 6M32 36l-2 6"/>',
  snow: '<path d="M14 30h20a8 8 0 0 0 0-16 11 11 0 0 0-21-2 8 8 0 0 0 1 18z"/><path d="M16 38h.1M24 41h.1M32 38h.1M20 44h.1M28 44h.1" stroke-width="4" stroke-linecap="round"/>',
  storm: '<path d="M14 30h20a8 8 0 0 0 0-16 11 11 0 0 0-21-2 8 8 0 0 0 1 18z"/><path d="M25 32l-5 7h6l-4 7"/>',
  fog: '<path d="M8 20h32M6 27h36M10 34h28"/>',
};
const WMO = { 0: "vedro", 1: "pretežno vedro", 2: "delimično oblačno", 3: "oblačno", 45: "magla", 48: "magla", 51: "rosulja", 53: "rosulja", 55: "rosulja", 61: "slaba kiša", 63: "kiša", 65: "jaka kiša", 71: "slab sneg", 73: "sneg", 75: "jak sneg", 80: "pljuskovi", 81: "pljuskovi", 82: "jaki pljuskovi", 95: "grmljavina", 96: "grmljavina", 99: "grmljavina" };

function iconFor(code) {
  if (code === 0 || code === 1) return "sun";
  if (code === 2) return "part";
  if (code === 3) return "cloud";
  if (code === 45 || code === 48) return "fog";
  if (code >= 71 && code <= 77 || code === 85 || code === 86) return "snow";
  if (code >= 95) return "storm";
  return "rain";
}

function svgIcon(code) {
  const ns = "http://www.w3.org/2000/svg";
  const s = document.createElementNS(ns, "svg");
  s.setAttribute("viewBox", "0 0 48 48");
  s.setAttribute("class", "wx-icon");
  s.innerHTML = ICONS[iconFor(code)]; // static, trusted markup
  return s;
}

async function loadWeather() {
  const box = $("weather");
  try {
    const res = await api("/api/weather");
    const d = await res.json();
    if (d.error) throw new Error(d.error);
    const c = d.current;
    const now = el("div", "wx-now");
    const info = el("div");
    info.append(el("div", "temp", Math.round(c.temperature_2m) + "°"), el("div", "desc", `${WMO[c.weather_code] || ""} · oseća se ${Math.round(c.apparent_temperature)}° · vetar ${Math.round(c.wind_speed_10m)} km/h`));
    now.append(svgIcon(c.weather_code), info);
    const days = el("div", "wx-days");
    d.daily.time.slice(0, 4).forEach((day, i) => {
      const cell = el("div");
      const label = i === 0 ? "danas" : SHORT_DAYS[new Date(day + "T12:00").getDay()];
      cell.append(el("div", "d", label), svgIcon(d.daily.weather_code[i]),
        el("div", "t", `${Math.round(d.daily.temperature_2m_max[i])}° / ${Math.round(d.daily.temperature_2m_min[i])}°`),
        el("div", "p", `☂ ${d.daily.precipitation_probability_max[i] || 0}%`));
      days.appendChild(cell);
    });
    box.replaceChildren(now, days);
  } catch (e) {
    box.replaceChildren(el("div", "empty", "Prognoza trenutno nije dostupna."));
  }
}

async function loadCalendar() {
  const ul = $("calendar");
  try {
    const res = await api("/api/calendar");
    const d = await res.json();
    ul.replaceChildren();
    if (!d.connected) { ul.appendChild(el("li", "empty", "Kalendar nije povezan.")); return; }
    if (!d.events.length) { ul.appendChild(el("li", "empty", "Danas nema događaja.")); return; }
    for (const e of d.events) {
      const [when, ...rest] = e.split(" ");
      const li = el("li");
      li.append(el("span", "when", when), el("span", "grow", rest.join(" ")));
      ul.appendChild(li);
    }
  } catch (_) {
    ul.replaceChildren(el("li", "empty", "Kalendar trenutno nije dostupan."));
  }
}

// ------------------------------------------------------- live events ----
let source = null;
function connectEvents() {
  if (source) source.close();
  source = new EventSource(`/api/events?t=${encodeURIComponent(TOKEN)}`);
  source.onopen = () => $("liveDot").classList.add("ok");
  source.onerror = () => $("liveDot").classList.remove("ok");
  source.addEventListener("notice", (ev) => {
    const n = JSON.parse(ev.data);
    const ul = $("feed");
    const empty = ul.querySelector(".empty");
    if (empty) empty.remove();
    ul.prepend(feedItem(n));
    if (!n.held && n.kind !== "action") toast(n.title, n.text ? n.text.slice(0, 160) : "");
    if (n.kind === "reminder" || n.kind === "nudge") loadState().catch(() => {});
  });
  source.addEventListener("action", (ev) => { upsertAction(JSON.parse(ev.data)); toast("Novi nacrt", "Čeka tvoje odobrenje."); });
  source.addEventListener("action_update", (ev) => upsertAction(JSON.parse(ev.data)));
  source.addEventListener("status", (ev) => { state = Object.assign(state || {}, JSON.parse(ev.data)); renderStatus(); });
  source.addEventListener("chat", (ev) => {
    const m = JSON.parse(ev.data);
    if (m.origin === CLIENT_ID) return; // we already showed our own messages
    addMessage(m.role, m.text);
  });
}

// --------------------------------------------------------------- wire ----
function wire() {
  $("reactor").onclick = listen;
  $("composer").onsubmit = (e) => {
    e.preventDefault();
    const v = $("input").value;
    $("input").value = "";
    sendText(v);
  };
  $("btnStop").onclick = () => sendText(state && state.paused ? "/nastavi" : "/stop");
  $("btnDnd").onclick = () => sendText(state && state.dnd ? "/dnd off" : "/dnd on");
  $("btnBrief").onclick = () => sendText("/danas");
  $("btnGoogle").onclick = () => { location.href = `/api/google/login?t=${encodeURIComponent(TOKEN)}`; };
  document.querySelectorAll("[data-mode]").forEach((b) => (b.onclick = () => sendText("/rezim " + b.dataset.mode)));
  $("tokenForm").onsubmit = (e) => {
    e.preventDefault();
    TOKEN = $("tokenInput").value.trim();
    try { localStorage.setItem("jarvis_token", TOKEN); } catch (_) { /* ignore */ }
    $("tokenOverlay").classList.add("hidden");
    start();
  };
}

async function start() {
  try {
    await loadState();
  } catch (e) {
    return;
  }
  connectEvents();
  loadWeather();
  loadCalendar();
  setInterval(loadWeather, 15 * 60 * 1000);
  setInterval(loadCalendar, 5 * 60 * 1000);
  setInterval(() => loadState().catch(() => {}), 60 * 1000);
}

initToken();
wire();
renderDays();
tick();
setInterval(tick, 1000);
if (!TOKEN) showTokenPrompt(); else start();
