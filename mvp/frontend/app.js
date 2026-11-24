// EchoMe MVP frontend. Plain JavaScript, no build step. Talks only to the local backend.
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
const api = async (path, opts = {}) => {
  const res = await fetch(path, {
    headers: opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {},
    ...opts,
    body: opts.body && !(opts.body instanceof FormData) ? JSON.stringify(opts.body) : opts.body,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  return res.headers.get("content-type")?.includes("json") ? res.json() : res;
};
const toast = (msg) => {
  const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), 2600);
};
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmtTime = (iso) => iso ? new Date(iso).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" }) : "";

let STATE = null;
let PENDING = null;      // negotiation result waiting for accept
let WHY_FOR = null;      // promise id waiting for a why-clip
let lastReply = "";

// ------------------------------------------------------------------ tabs
$$(".tab").forEach((b) => b.addEventListener("click", () => {
  $$(".tab").forEach((x) => x.classList.toggle("active", x === b));
  $$(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === "tab-" + b.dataset.tab));
  if (b.dataset.tab === "manual") loadManual();
  if (b.dataset.tab === "about") loadFacts();
  if (b.dataset.tab === "data") loadData();
}));

// ------------------------------------------------------------------ buddy (Pip)
const BUDDY_LINES = {
  groggy: "Rough night. Let's keep today light.",
  calm: "Steady day. Let's pick one thing that matters.",
  happy: "You're well rested. Good day for deep work!",
  sleepy: "Rest is part of the plan. Tomorrow we go again.",
  caring: "I'm here. One small step at a time.",
};
function buddySVG(mood) {
  const body = '<path d="M75 22 C112 22 128 52 126 82 C124 110 104 120 75 120 C46 120 26 110 24 82 C22 52 38 22 75 22Z" fill="#8C7CF0"/>' +
    '<path d="M75 22 C112 22 128 52 126 82" fill="none" stroke="#fff" stroke-opacity=".35" stroke-width="5" stroke-linecap="round"/>' +
    '<circle cx="44" cy="88" r="6" fill="#F7A8C0" opacity=".7"/><circle cx="106" cy="88" r="6" fill="#F7A8C0" opacity=".7"/>';
  const faces = {
    groggy: '<path d="M50 72 q9 5 18 0 M84 72 q9 5 18 0" stroke="#1F1B2E" stroke-width="4" fill="none" stroke-linecap="round"/><path d="M46 64 h24 M82 64 h24" stroke="#6A59D9" stroke-width="3" stroke-linecap="round"/><ellipse cx="76" cy="96" rx="7" ry="5" fill="#1F1B2E"/><text x="118" y="36" font-size="15" font-weight="700" fill="#6A59D9">z</text><text x="130" y="22" font-size="11" font-weight="700" fill="#6A59D9">z</text>',
    calm: '<circle cx="58" cy="72" r="6" fill="#1F1B2E"/><circle cx="94" cy="72" r="6" fill="#1F1B2E"/><path d="M66 94 q10 6 20 0" stroke="#1F1B2E" stroke-width="3.5" fill="none" stroke-linecap="round"/>',
    happy: '<path d="M50 74 q8 -9 16 0 M86 74 q8 -9 16 0" stroke="#1F1B2E" stroke-width="4" fill="none" stroke-linecap="round"/><path d="M62 92 q14 14 28 0" stroke="#1F1B2E" stroke-width="4" fill="#fff" stroke-linecap="round"/><path d="M118 40 l6 -10 M126 50 l10 -4" stroke="#FFC94D" stroke-width="3" stroke-linecap="round"/>',
    sleepy: '<path d="M52 76 q8 6 16 0 M84 76 q8 6 16 0" stroke="#1F1B2E" stroke-width="3.5" fill="none" stroke-linecap="round"/><path d="M68 94 q8 5 16 0" stroke="#1F1B2E" stroke-width="3" fill="none" stroke-linecap="round"/><path d="M18 100 C40 90 110 90 132 100 L132 124 C110 130 40 130 18 124Z" fill="#7FCBAE"/><path d="M56 30 q19 -24 38 0" fill="#F07A5A"/><circle cx="75" cy="10" r="5" fill="#fff"/>',
    caring: '<circle cx="58" cy="72" r="8" fill="#fff"/><circle cx="94" cy="72" r="8" fill="#fff"/><circle cx="59" cy="74" r="4.5" fill="#1F1B2E"/><circle cx="95" cy="74" r="4.5" fill="#1F1B2E"/><path d="M50 58 q8 -5 16 0 M86 58 q8 -5 16 0" stroke="#1F1B2E" stroke-width="3" fill="none" stroke-linecap="round"/><path d="M64 96 q12 8 24 0" stroke="#1F1B2E" stroke-width="3.5" fill="none" stroke-linecap="round"/>',
  };
  return `<svg viewBox="0 0 150 135" role="img" aria-label="Pip looks ${mood}"><ellipse cx="75" cy="128" rx="44" ry="6" fill="#000" opacity=".08"/><g class="bob">${body}${faces[mood] || faces.calm}</g></svg>`;
}

// ------------------------------------------------------------------ render Today
function renderState(s) {
  STATE = s;
  const d = new Date();
  $("#date-line").textContent = d.toLocaleDateString([], { weekday: "long", day: "numeric", month: "short" });
  const hour = d.getHours();
  $("#greeting").textContent = `${hour < 12 ? "Morning" : hour < 17 ? "Afternoon" : "Evening"}, ${s.name}`;
  $("#manual-title").textContent = `${s.name}'s Manual`;
  $("#ai-chip").textContent = s.llm.available ? `AI: local ${s.llm.model}` : "AI: built-in rules";
  $("#ai-chip").title = s.llm.available ? "Running on your device via Ollama" : "Install Ollama + gemma3:4b for local AI. Rules work offline.";

  $("#buddy").innerHTML = buddySVG(s.buddy);
  $("#buddy-chip").textContent = `Pip · ${s.buddy}`;
  $("#buddy-line").textContent = `"${BUDDY_LINES[s.buddy] || BUDDY_LINES.calm}"`;

  const b = s.body;
  $("#cap-min").textContent = `~${s.capacity_minutes} focused min`;
  const chip = $("#cap-chip"); chip.textContent = b.label.toUpperCase(); chip.className = "chip " + b.label.toLowerCase();
  $("#cap-bar").style.width = Math.min(100, Math.round((s.capacity_minutes / 240) * 100)) + "%";
  $("#cap-bar").style.background = b.label === "Low" ? "var(--amber)" : b.label === "High" ? "var(--mint)" : "var(--indigo)";
  $("#reasons").innerHTML = b.reasons.map((r) => `<li>${esc(r[0].toUpperCase() + r.slice(1))}</li>`).join("");

  const t = s.today || {};
  $("#m-sleep").textContent = t.sleep_hours != null ? `${t.sleep_hours}h` : "–";
  const sd = t.sleep_hours != null ? +(t.sleep_hours - s.baseline.sleep).toFixed(1) : null;
  $("#m-sleep-d").textContent = sd == null ? "" : `${sd >= 0 ? "+" : ""}${sd}h vs usual`;
  $("#m-sleep-d").className = "d " + (sd != null && sd < -1 ? "bad" : "good");
  $("#m-hr").textContent = t.resting_hr ? `${t.resting_hr} bpm` : "–";
  const hd = t.resting_hr ? t.resting_hr - s.baseline.rhr : null;
  $("#m-hr-d").textContent = hd == null ? "" : `${hd >= 0 ? "+" : ""}${hd} vs usual`;
  $("#m-hr-d").className = "d " + (hd != null && hd > 4 ? "bad" : "good");
  $("#m-stress").textContent = t.stress != null ? `${t.stress}/100` : "–";
  $("#m-trust").textContent = s.self_trust;

  $("#active-list").innerHTML = s.active_promises.length ? s.active_promises.slice().reverse().map((p) => `
    <li><div class="t"><div>${esc(p.final_text)}</div><div class="meta">Due ${fmtTime(p.due_at)}${p.why_clip ? " · 🎙 why recorded" : p.why_text ? " · why saved" : ""}</div></div>
    <button class="btn small ghost" data-status="kept" data-id="${p.id}">✓ Kept</button>
    <button class="btn small ghost" data-status="broken" data-id="${p.id}">✗ Missed</button></li>`).join("")
    : `<li class="empty">No active promise. Make one above.</li>`;
  $("#recent-list").innerHTML = s.recent_promises.map((p) => `
    <li><span class="status ${p.status}">${p.status}</span><div class="t">${esc(p.final_text)}</div><span class="meta">${fmtTime(p.created_at)}</span></li>`).join("");
}
const refresh = async () => renderState(await api("/api/state"));

// ------------------------------------------------------------------ watch sync
const PRESETS = {
  rough: { sleep_hours: 4.5, resting_hr: 74, steps: 2100, stress: 68 },
  rested: { sleep_hours: 8.1, resting_hr: 63, steps: 7400, stress: 32 },
  stressed: { sleep_hours: 6.6, resting_hr: 71, steps: 11800, stress: 82 },
};
$$("[data-sync]").forEach((b) => b.addEventListener("click", async () => {
  renderState(await api("/api/health/sync", { method: "POST", body: PRESETS[b.dataset.sync] }));
  toast("Watch synced");
}));
$("#csv").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  try { const r = await api("/api/health/import", { method: "POST", body: fd }); toast(`Imported ${r.imported} days`); refresh(); }
  catch (err) { toast(err.message); }
  e.target.value = "";
});

// ------------------------------------------------------------------ promise negotiation
$("#promise-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("#promise-text").value.trim(); if (!text) return;
  const btn = e.submitter; btn.disabled = true; btn.textContent = "Thinking…";
  try {
    PENDING = await api("/api/promise/propose", { method: "POST", body: { text } });
    $("#neg-message").textContent = PENDING.message;
    $("#neg-suggested").value = PENDING.suggested;
    $("#neg-chips").innerHTML = `<span class="chip">${esc(PENDING.if_then)}</span><span class="chip ${PENDING.body_label.toLowerCase()}">Capacity: ${PENDING.capacity_minutes} min</span><span class="chip muted">Needs ~${PENDING.est_minutes} min</span>`;
    $("#neg-accept").textContent = PENDING.verdict === "fits" ? "Lock it in" : "Accept suggestion";
    $("#negotiation").classList.remove("hidden");
  } catch (err) { toast(err.message); }
  btn.disabled = false; btn.textContent = "Check it";
});
async function acceptPromise(finalText) {
  const p = await api("/api/promise/accept", { method: "POST", body: {
    original: PENDING.original, final_text: finalText, est_minutes: PENDING.est_minutes,
    capacity_minutes: PENDING.capacity_minutes, due_at: PENDING.due_at } });
  $("#negotiation").classList.add("hidden"); $("#promise-text").value = "";
  WHY_FOR = p.id; $("#why-card").classList.remove("hidden"); $("#why-text").value = "";
  $("#rec-preview").classList.add("hidden"); recBlob = null;
  refresh();
}
$("#neg-accept").addEventListener("click", () => acceptPromise($("#neg-suggested").value.trim() || PENDING.suggested));
$("#neg-keep").addEventListener("click", () => acceptPromise(PENDING.original));

// ------------------------------------------------------------------ why-clip recording (stays on device)
let recorder = null, recChunks = [], recBlob = null;
$("#rec-btn").addEventListener("click", async () => {
  if (recorder && recorder.state === "recording") { recorder.stop(); return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recorder = new MediaRecorder(stream); recChunks = [];
    recorder.ondataavailable = (e) => recChunks.push(e.data);
    recorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      recBlob = new Blob(recChunks, { type: recorder.mimeType || "audio/webm" });
      const a = $("#rec-preview"); a.src = URL.createObjectURL(recBlob); a.classList.remove("hidden");
      $("#rec-btn").classList.remove("on"); $("#rec-label").textContent = "Re-record";
    };
    recorder.start(); $("#rec-btn").classList.add("on"); $("#rec-label").textContent = "Stop";
    setTimeout(() => recorder && recorder.state === "recording" && recorder.stop(), 10000);
  } catch (err) { toast("Microphone not available. You can type your why instead."); }
});
$("#why-save").addEventListener("click", async () => {
  const text = $("#why-text").value.trim();
  if (!recBlob && !text) { toast("Record or type your why first"); return; }
  if (recBlob) {
    const fd = new FormData(); fd.append("file", recBlob, "why.webm");
    await api(`/api/promise/${WHY_FOR}/why?why_text=${encodeURIComponent(text)}`, { method: "POST", body: fd });
  } else {
    await api(`/api/promise/${WHY_FOR}/why-text`, { method: "POST", body: { why_text: text } });
  }
  $("#why-card").classList.add("hidden"); toast("Saved. I'll remind you in your own words."); refresh();
});
$("#why-skip").addEventListener("click", () => $("#why-card").classList.add("hidden"));

// ------------------------------------------------------------------ status, drift & check-ins
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-status]"); if (!b) return;
  renderState(await api(`/api/promise/${b.dataset.id}/status`, { method: "POST", body: { status: b.dataset.status } }));
  toast(b.dataset.status === "kept" ? "Nice! Self-trust +3" : "Noted. Smaller promise next time?");
});
function showResponse(r) {
  const card = $("#response");
  card.className = "card response " + r.mode;
  $("#mode-badge").textContent = { push: "PUSH", protect: "PROTECT", gentle: "GENTLE", neutral: "NOTED" }[r.mode];
  $("#response-text").textContent = r.reply; lastReply = r.reply;
  const echo = $("#echo");
  if (r.mode === "push" && (r.why_clip || r.why_text)) {
    echo.classList.remove("hidden");
    const a = $("#echo-audio");
    if (r.why_clip) { a.classList.remove("hidden"); a.src = r.why_clip; a.play().catch(() => {}); } else { a.classList.add("hidden"); }
    $("#echo-text").textContent = r.why_text ? `"${r.why_text}"` : "";
  } else echo.classList.add("hidden");
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  refresh();
}
$("#drift-btn").addEventListener("click", async () => showResponse(await api("/api/drift", { method: "POST" })));
$("#checkin-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("#checkin-text").value.trim(); if (!text) return;
  $("#checkin-text").value = "";
  showResponse(await api("/api/checkin", { method: "POST", body: { text } }));
});
$$("[data-say]").forEach((b) => b.addEventListener("click", async () =>
  showResponse(await api("/api/checkin", { method: "POST", body: { text: b.dataset.say } }))));

// Pip's voice: local browser voice by default; ElevenLabs only if the backend has a key (opt-in)
$("#hear-btn").addEventListener("click", async () => {
  if (!lastReply) return;
  try {
    const res = await fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: lastReply }) });
    if (res.headers.get("content-type")?.includes("audio")) { new Audio(URL.createObjectURL(await res.blob())).play(); toast("Pip's voice by ElevenLabs"); return; }
  } catch (_) {}
  if ("speechSynthesis" in window) { speechSynthesis.cancel(); speechSynthesis.speak(new SpeechSynthesisUtterance(lastReply)); }
});

// ------------------------------------------------------------------ Manual
async function loadManual() {
  const m = await api("/api/manual");
  $("#svd").innerHTML = m.said_vs_data.map((s) => `<div class="svd"><b>WHAT YOU SAID VS. YOUR DATA</b>${esc(s)}</div>`).join("");
  $("#rules").innerHTML = m.rules.length ? m.rules.map((r) => `
    <li class="${r.status}"><div class="t"><b>${esc(r.text)}</b><span>${esc(r.evidence)}</span></div>
    ${r.status === "confirmed" ? '<span class="status kept">That\'s me</span>' :
      `<button class="btn small primary" data-rule="${r.key}" data-rs="confirmed">That's me</button>
       <button class="btn small ghost" data-rule="${r.key}" data-rs="rejected">Not me</button>`}</li>`).join("")
    : `<li class="empty">Not enough history yet. Keep making promises and I'll learn your patterns.</li>`;
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-rule]"); if (!b) return;
  await api(`/api/manual/${b.dataset.rule}`, { method: "POST", body: { status: b.dataset.rs } });
  loadManual();
});

// ------------------------------------------------------------------ About Me
let LEARNED = [];
async function loadFacts() {
  const facts = await api("/api/aboutme");
  $("#facts").innerHTML = facts.map((f) => `<li><span class="cat">${esc(f.category)}</span><div class="t">${esc(f.text)}</div>
    ${f.temporary ? '<span class="status moved">expires</span>' : ""}<button class="btn small ghost" data-del="${f.id}">Forget</button></li>`).join("")
    || `<li class="empty">Nothing yet. Tell EchoMe about yourself above.</li>`;
}
$("#intro-btn").addEventListener("click", async () => {
  const text = $("#intro-text").value.trim(); if (!text) return;
  const r = await api("/api/aboutme/extract", { method: "POST", body: { text } });
  LEARNED = r.facts;
  $("#learned").innerHTML = LEARNED.length ? LEARNED.map((f, i) => `<li><input type="checkbox" checked data-i="${i}"><span class="cat">${esc(f.category)}</span><div class="t">${esc(f.text)}</div></li>`).join("")
    : `<li class="empty">I couldn't find clear facts. Try short sentences like "I want to…" or "I get distracted by…".</li>`;
  $("#learned-card").classList.remove("hidden");
});
$("#learned-save").addEventListener("click", async () => {
  const keep = [...$$("#learned input:checked")].map((c) => LEARNED[+c.dataset.i]);
  await api("/api/aboutme/confirm", { method: "POST", body: { facts: keep } });
  $("#learned-card").classList.add("hidden"); $("#intro-text").value = ""; toast(`Saved ${keep.length} facts`); loadFacts();
});
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-del]"); if (!b) return;
  await api(`/api/aboutme/${b.dataset.del}`, { method: "DELETE" }); loadFacts();
});

// ------------------------------------------------------------------ My Data
async function loadData() {
  const d = await api("/api/mydata");
  const total = Object.values(d.counts).reduce((a, b) => a + b, 0);
  $("#data-summary").textContent = `🔒 ${total} records and ${d.clips} voice clips, all on this device · no raw personal data sent to the cloud`;
  $("#data-where").textContent = `Stored in ${d.location} · AI: ${d.llm}`;
  const names = { health_logs: "Days of watch data", promises: "Promises", checkins: "Check-ins", about_me: "About Me facts", manual_rules: "Manual rules" };
  $("#data-counts").innerHTML = Object.entries(d.counts).map(([k, v]) => `<li><span>${names[k]}</span><b>${v}</b></li>`).join("");
  loadCloud();
}
async function loadCloud() {
  const c = await api("/api/cloud/status");
  const el = $("#el-status");
  el.textContent = c.elevenlabs.configured ? "Connected" : "Off · using device voice";
  el.className = "chip " + (c.elevenlabs.configured ? "on" : "muted");
  $("#el-preview").textContent = `"${c.preview_filtered_text}"`;
  const aw = $("#aws-status");
  aw.textContent = c.aws.configured ? `Connected · ${c.aws.bucket}` : "Off · backups saved locally (encrypted)";
  aw.className = "chip " + (c.aws.configured ? "on" : "muted");
}
$("#el-test").addEventListener("click", async () => {
  const text = "Hi, I'm Pip. You've had a tiring day, so let's do two chapters tonight and the rest tomorrow.";
  const res = await fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
  if (res.headers.get("content-type")?.includes("audio")) {
    new Audio(URL.createObjectURL(await res.blob())).play(); $("#el-result").textContent = "Playing ElevenLabs voice";
  } else {
    if ("speechSynthesis" in window) { speechSynthesis.cancel(); speechSynthesis.speak(new SpeechSynthesisUtterance(text)); }
    $("#el-result").textContent = "Playing device voice (add an ElevenLabs key to switch)";
  }
});
$("#aws-backup").addEventListener("click", async () => {
  const out = $("#aws-result"); out.textContent = "Encrypting…";
  try {
    const r = await api("/api/cloud/backup", { method: "POST", body: { passphrase: $("#aws-pass").value } });
    out.innerHTML = r.stored === "aws-s3"
      ? `✅ Encrypted and uploaded to <b>${esc(r.location)}</b> (${Math.round(r.bytes / 1024)} KB)`
      : `✅ Encrypted backup saved: <a href="/api/cloud/backup/${esc(r.name)}">${esc(r.location)}</a>. Set ECHOME_S3_BUCKET to upload to AWS.`;
  } catch (err) { out.textContent = "⚠️ " + err.message; }
});
$("#aws-restore").addEventListener("click", async () => {
  const out = $("#aws-result"); out.textContent = "Decrypting…";
  try {
    const r = await api("/api/cloud/restore", { method: "POST", body: { passphrase: $("#aws-pass").value } });
    out.textContent = `✅ Restored from ${r.restored_from}`; loadData(); refresh();
  } catch (err) { out.textContent = "⚠️ " + err.message; }
});

$("#forget-btn").addEventListener("click", async () => {
  if (!window.confirm("Delete ALL your EchoMe data and voice clips from this device? This cannot be undone.")) return;
  await api("/api/forget", { method: "POST" }); toast("Everything forgotten"); loadData(); refresh();
});
$("#reset-btn").addEventListener("click", async () => {
  await api("/api/demo/reset", { method: "POST" }); toast("Sample persona reloaded"); loadData(); refresh();
});

refresh();
