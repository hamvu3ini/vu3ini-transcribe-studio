/* VU3INI Transcribe Studio — front end (plain JavaScript, no external libraries) */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clock = (t) => { t = Math.max(0, t || 0); const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = Math.floor(t % 60);
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`; };
const clockMs = (t) => clock(t) + "." + String(Math.floor(((t || 0) % 1) * 10));

const LANGS = [["auto", "Automatic"], ["as", "Assamese"], ["hi", "Hindi"], ["bn", "Bengali"], ["en", "English"],
  ["mr", "Marathi"], ["ne", "Nepali"], ["gu", "Gujarati"], ["pa", "Punjabi"], ["or", "Odia"], ["ta", "Tamil"], ["te", "Telugu"],
  ["kn", "Kannada"], ["ml", "Malayalam"], ["ur", "Urdu"], ["sa", "Sanskrit"]];
const LANG_NAME = Object.fromEntries(LANGS);
const TR_TARGETS = [["eng_Latn", "English"], ["asm_Beng", "Assamese"], ["hin_Deva", "Hindi"], ["ben_Beng", "Bengali"]];
const SPK_COLORS = ["#1f6fd1", "#c0392b", "#2e7d32", "#7b3fa0", "#a86b00", "#00796b", "#c2185b", "#455a64"];

const S = { info: null, settings: null, packs: [], jobs: [], jobState: {}, P: null, dirty: false, sel: null,
  peaks: [], roman: null, view: "home" };

/* ------------------------------------------------------------------ helpers */
async function api(path, opts = {}) {
  const o = { ...opts };
  if (o.json !== undefined) { o.body = JSON.stringify(o.json); o.headers = { "Content-Type": "application/json" }; delete o.json; }
  const r = await fetch(path, o);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (e) { /* ignore */ }
    throw new Error(msg);
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}
let toastTimer;
function toast(msg, err = false, ms = 3800) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast" + (err ? " err" : "");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.add("hidden"), ms);
}
const fail = (e) => toast(e.message || String(e), true, 6000);
function openModal(id) { $("#" + id).classList.remove("hidden"); }
function closeModal(id) { $("#" + id).classList.add("hidden"); }
function fillSelect(sel, items, value) {
  sel.innerHTML = items.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("");
  if (value !== undefined && items.some(([v]) => v === value)) sel.value = value;
}

/* ------------------------------------------------------------------ splash */
function initSplash() {
  const ok = $("#splashOk");
  let left = 3;
  const start = performance.now();
  const tick = setInterval(() => {
    left = Math.max(0, 3 - Math.floor((performance.now() - start) / 1000));
    ok.textContent = left ? `Agree / OK (${left})` : "Agree / OK";
    if (!left) { ok.disabled = false; clearInterval(tick); }
  }, 100);
  ok.addEventListener("click", () => {
    if (performance.now() - start < 3000) return; // never before 3 s
    $("#splash").classList.add("hidden");
    document.body.dataset.agreed = "1";
  });
  $("#splashExit").addEventListener("click", () => shutdown(false));
  $("#terms").focus();
}

async function shutdown(ask = true) {
  if (ask && !confirm("Shut down VU3INI Transcribe Studio? Running jobs will be stopped.")) return;
  if (S.dirty && ask && !confirm("You have unsaved changes. Shut down anyway?")) return;
  try { await api("/api/shutdown", { method: "POST" }); } catch (e) { /* server already gone */ }
  $$(".backdrop").forEach((b) => b.classList.add("hidden"));
  openModal("closedScreen");
  setTimeout(() => { try { window.close(); } catch (e) { /* ignore */ } }, 600);
}

/* ------------------------------------------------------------------ theme, menus, tabs */
function initChrome() {
  $("#themeBtn").addEventListener("click", () => {
    const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem("vts-theme", t); } catch (e) { /* ignore */ }
    drawWave();
  });
  document.addEventListener("click", (e) => {
    const wrap = e.target.closest(".menu-wrap");
    $$(".menu.open").forEach((m) => { if (!wrap || !wrap.contains(m)) m.classList.remove("open"); });
    if (e.target.matches(".menu-wrap > .btn")) e.target.nextElementSibling.classList.toggle("open");
    const g = e.target.closest("[data-goto]");
    if (g) { e.preventDefault(); go(g.dataset.goto); }
    const c = e.target.closest("[data-close]");
    if (c) closeModal(c.dataset.close);
  });
  $("#helpMenu").addEventListener("click", (e) => {
    const a = e.target.dataset.act; if (!a) return;
    $("#helpMenu").classList.remove("open");
    if (a === "help") openHelp(); else if (a === "about") openAbout(); else openModal("keysModal");
  });
  $("#tabs").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) go(b.dataset.view); });
  $("#shutdownBtn").addEventListener("click", () => shutdown(true));
  document.addEventListener("keydown", (e) => {
    if (e.key === "F1") { e.preventDefault(); openHelp(); }
    if (e.key === "Escape") ["helpModal", "aboutModal", "keysModal"].forEach(closeModal);
  });
  window.addEventListener("beforeunload", (e) => { if (S.dirty) { e.preventDefault(); e.returnValue = ""; } });
}

function go(view) {
  if (S.view === "editor" && view !== "editor" && S.dirty && !confirm("Leave without saving your changes?")) return;
  if (view !== "editor") { $("#audio").pause(); if (S.view === "editor") S.dirty = false; }
  S.view = view;
  $$(".view").forEach((v) => v.classList.toggle("on", v.id === "view-" + view));
  $$("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.view === view));
  if (view === "projects") loadProjects();
  if (view === "packs") loadPacks();
  if (view === "settings") loadSettings();
  if (view === "home") loadRecent();
  window.scrollTo(0, 0);
}

/* ------------------------------------------------------------------ info & selects */
async function refreshInfo() {
  S.info = await api("/api/info");
  const engines = [["auto", "Automatic (route by language)"], ...S.info.asr_packs.map((p) => [p.id, p.name])];
  $$(".engine-select").forEach((s) => fillSelect(s, engines, s.value || "auto"));
  $("#noPackWarn").classList.toggle("hidden", S.info.asr_packs.length > 0);
}
function initSelects() {
  $$(".lang-select").forEach((s) => fillSelect(s, LANGS, "auto"));
  fillSelect($("#trTarget"), TR_TARGETS, "eng_Latn");
  fillSelect($("#sTr"), TR_TARGETS, "eng_Latn");
}

/* ------------------------------------------------------------------ home: upload & queue */
function initHome() {
  const drop = $("#drop"), input = $("#fileInput");
  drop.addEventListener("click", () => input.click());
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") input.click(); });
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); uploadFiles(e.dataTransfer.files); });
  input.addEventListener("change", () => { uploadFiles(input.files); input.value = ""; });
  $("#batchBtn").addEventListener("click", async () => {
    try {
      const r = await api("/api/batch", { method: "POST", json: { folder: $("#batchFolder").value, recursive: $("#batchRec").checked, ...homeOpts() } });
      toast(`Added ${r.jobs.length} file(s) to the queue.`); pollJobs();
    } catch (e) { fail(e); }
  });
  $("#pauseBtn").addEventListener("click", async () => {
    const paused = (await api("/api/jobs")).paused;
    await api(`/api/queue/${paused ? "resume" : "pause"}`, { method: "POST" }); pollJobs();
  });
  $("#clearBtn").addEventListener("click", async () => { await api("/api/queue/clear", { method: "POST" }); pollJobs(); });
  $("#jobList").addEventListener("click", async (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.cancel) { await api(`/api/jobs/${b.dataset.cancel}/cancel`, { method: "POST" }); pollJobs(); }
    if (b.dataset.open) openProject(b.dataset.open);
  });
}
function homeOpts() {
  return { language: $("#optLang").value, engine: $("#optEngine").value, diarize: $("#optDiar").checked,
    max_speakers: +$("#optSpk").value || 0, denoise: $("#optDenoise").checked, normalize: $("#optNorm").checked, trim_silence: $("#optTrim").checked };
}
async function uploadFiles(files) {
  const o = homeOpts();
  for (const f of files) {
    const fd = new FormData();
    fd.append("file", f);
    for (const [k, v] of Object.entries(o)) fd.append(k, typeof v === "boolean" ? (v ? "1" : "0") : v);
    try { toast(`Uploading ${f.name}…`); await api("/api/projects", { method: "POST", body: fd }); }
    catch (e) { fail(e); }
  }
  pollJobs(); loadRecent();
}

let pollTimer = null;
async function pollJobs() {
  clearTimeout(pollTimer);
  try {
    const r = await api("/api/jobs");
    S.jobs = r.jobs;
    $("#pauseBtn").textContent = r.paused ? "Resume queue" : "Pause queue";
    renderJobs(r.jobs);
    for (const j of r.jobs) {
      const before = S.jobState[j.id];
      if (before && before !== j.status && ["done", "failed", "cancelled"].includes(j.status)) onJobFinished(j);
      S.jobState[j.id] = j.status;
    }
    const active = r.jobs.some((j) => j.status === "running" || j.status === "queued");
    pollTimer = setTimeout(pollJobs, active ? 1000 : 3000);
  } catch (e) { pollTimer = setTimeout(pollJobs, 4000); }
}
function renderJobs(jobs) {
  const el = $("#jobList");
  if (!jobs.length) { el.innerHTML = '<p class="muted">Nothing in the queue.</p>'; return; }
  el.innerHTML = jobs.map((j) => `
    <div class="job ${j.status}">
      <div class="row between"><b>${esc(j.title)}</b><span class="small muted">${esc(j.stage)}${j.eta != null ? " · about " + clock(j.eta) + " left" : ""}</span></div>
      <div class="bar"><div style="width:${Math.round(j.progress * 100)}%"></div></div>
      ${j.error ? `<div class="err">${esc(j.error)}</div>` : ""}
      ${j.notes && j.notes.length ? `<div class="small muted">${j.notes.map(esc).join(" · ")}</div>` : ""}
      <div class="row">${["queued", "running"].includes(j.status) ? `<button class="btn small" data-cancel="${j.id}">Cancel</button>` : ""}
        ${j.status === "done" && j.project_id && j.kind === "transcribe" ? `<button class="btn small primary" data-open="${j.project_id}">Open</button>` : ""}</div>
    </div>`).join("");
}
async function onJobFinished(j) {
  if (j.status === "failed") toast(`${j.title}: ${j.error}`, true, 7000);
  else if (j.status === "done") toast(`${j.title} — finished.`);
  if (j.kind === "pack") { await refreshInfo(); if (S.view === "packs") loadPacks(); $("#dlMsg").textContent = ""; }
  if (S.view === "home") loadRecent();
  if (S.P && j.project_id === S.P.id && j.status === "done") {
    if (j.kind === "burn") { window.location.href = `/api/projects/${S.P.id}/subtitled`; return; }
    if (S.dirty) toast("This project was updated in the background. Save or reload to see it.", false, 6000);
    else openProject(S.P.id, null, true);
  }
}

/* ------------------------------------------------------------------ projects */
function projCard(p) {
  return `<div class="pitem" data-id="${p.id}"><button class="del" title="Delete project" data-del="${p.id}">✕</button>
    <div class="t">${esc(p.name)}</div>
    <div class="meta">${esc(p.updated || p.created)} · ${clock(p.duration)} · ${esc(LANG_NAME[p.language] || p.language || "–")} · ${p.segments} segments · ${esc(p.status)}</div>
    <div>${(p.tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div></div>`;
}
function bindProjList(el) {
  el.onclick = async (e) => {
    const d = e.target.closest("[data-del]");
    if (d) { e.stopPropagation(); if (confirm("Delete this project and its audio permanently?")) { await api(`/api/projects/${d.dataset.del}`, { method: "DELETE" }); loadProjects(); loadRecent(); } return; }
    const it = e.target.closest(".pitem"); if (it) openProject(it.dataset.id);
  };
}
async function loadRecent() {
  const list = await api("/api/projects").catch(() => []);
  $("#recentList").innerHTML = list.slice(0, 8).map(projCard).join("") || '<p class="muted">No projects yet.</p>';
  bindProjList($("#recentList"));
}
async function loadProjects() {
  const list = await api("/api/projects");
  $("#projList").innerHTML = list.map(projCard).join("") || '<p class="muted">No projects yet.</p>';
  bindProjList($("#projList"));
}
function initProjects() {
  let t;
  $("#projSearch").addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(async () => {
      const q = $("#projSearch").value.trim();
      if (!q) { $("#searchHits").innerHTML = ""; return; }
      const hits = await api("/api/search?q=" + encodeURIComponent(q));
      const re = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
      $("#searchHits").innerHTML = hits.length ? `<div class="small muted">${hits.length} match(es)</div>` + hits.map((h) =>
        `<div class="hit" data-id="${h.id}" data-t="${h.start}"><b>${esc(h.name)}</b> <span class="mono small muted">${clock(h.start)}</span> — ${esc(h.text).replace(re, (m) => `<mark>${m}</mark>`)}</div>`).join("")
        : '<p class="muted">No matches.</p>';
    }, 250);
  });
  $("#searchHits").addEventListener("click", (e) => { const h = e.target.closest(".hit"); if (h) openProject(h.dataset.id, +h.dataset.t); });
}

/* ------------------------------------------------------------------ packs & settings */
async function loadPacks() {
  S.packs = await api("/api/packs");
  const TYPE = { "asr-ct2": "Speech recognition (CTranslate2)", "asr-hf": "Speech recognition (Hugging Face)", diarization: "Speaker diarization", translation: "Translation (IndicTrans2)", "gpu-runtime": "NVIDIA GPU runtime" };
  $("#packTbl tbody").innerHTML = S.packs.map((p) => `<tr><td><b>${esc(p.name)}</b><br><span class="small muted">${esc(p.id)} ${p.version ? "· v" + esc(p.version) : ""}</span></td>
    <td>${esc(TYPE[p.type] || p.type)}${p.direction ? "<br><span class='small muted'>" + esc(p.direction) + "</span>" : ""}</td>
    <td>${esc((p.languages || []).map((l) => l === "*" ? "Many (auto-detect)" : (LANG_NAME[l] || l)).join(", ") || "–")}</td>
    <td>${p.size_mb >= 1000 ? (p.size_mb / 1000).toFixed(2) + " GB" : p.size_mb + " MB"}</td><td class="small">${esc(p.license || "")}</td>
    <td><button class="btn small danger" data-rm="${esc(p.id)}">Remove</button></td></tr>`).join("") ||
    '<tr><td colspan="6" class="muted">No packs installed yet.</td></tr>';
  await renderLangEngines();
  loadCatalog();
  const i = S.info || (await api("/api/info"));
  $("#deviceInfo").textContent = `Processor in use: ${i.device === "cuda" ? "NVIDIA GPU" : "CPU"} (${i.compute_type}). ` +
    (i.cuda ? "A CUDA GPU is available." : "No CUDA GPU detected — install the NVIDIA GPU runtime pack to use your graphics card.") + ` Packs folder: ${i.packs_dir}`;
}
function autoPackFor(lang, asr) {
  return asr.find((p) => (p.preferred_for || []).includes(lang)) || asr.find((p) => (p.languages || []).includes(lang))
    || asr.find((p) => (p.languages || []).includes("*")) || asr[0];
}
async function renderLangEngines() {
  const s = S.settings || (S.settings = await api("/api/settings"));
  const le = s.language_engines || {};
  const asr = S.packs.filter((p) => p.type === "asr-ct2" || p.type === "asr-hf");
  const el = $("#langEngines");
  if (!asr.length) { el.innerHTML = '<p class="muted">Install a speech recognition pack first.</p>'; return; }
  el.innerHTML = LANGS.filter(([c]) => c !== "auto").map(([code, name]) => {
    const fits = asr.filter((p) => (p.languages || []).includes("*") || (p.languages || []).includes(code));
    const others = asr.filter((p) => !fits.includes(p));
    const auto = autoPackFor(code, asr);
    const cur = le[code] && asr.some((p) => p.id === le[code]) ? le[code] : "auto";
    const opt = (p) => `<option value="${esc(p.id)}" ${p.id === cur ? "selected" : ""}>${esc(p.name)}</option>`;
    return `<label>${esc(name)} <select data-lang="${code}" aria-label="Engine for ${esc(name)}">
      <option value="auto" ${cur === "auto" ? "selected" : ""}>Automatic${auto ? " (" + esc(auto.name) + ")" : ""}</option>
      ${fits.length ? `<optgroup label="Supports ${esc(name)}">${fits.map(opt).join("")}</optgroup>` : ""}
      ${others.length ? `<optgroup label="Other packs">${others.map(opt).join("")}</optgroup>` : ""}
    </select>${le[code] && le[code] !== "auto" && !asr.some((p) => p.id === le[code]) ? `<span class="note">Previously chosen pack “${esc(le[code])}” is not installed.</span>` : ""}</label>`;
  }).join("");
}
async function saveLangEngines(reset = false) {
  const le = {};
  if (!reset) $$("#langEngines select").forEach((sel) => { if (sel.value !== "auto") le[sel.dataset.lang] = sel.value; });
  try {
    S.settings = await api("/api/settings", { method: "POST", json: { language_engines: le } });
    await renderLangEngines();
    $("#leMsg").textContent = reset ? "All languages set to Automatic." : "Saved."; setTimeout(() => ($("#leMsg").textContent = ""), 2500);
  } catch (e) { fail(e); }
}
async function loadCatalog() {
  try {
    const r = await api("/api/packs/catalog");
    S.catalog = r;
    $("#catTbl tbody").innerHTML = r.catalog.map((c) => `<tr>
      <td><input type="checkbox" data-pack="${esc(c.id)}" aria-label="Get ${esc(c.name)}"></td>
      <td><b>${esc(c.name)}</b>${c.gated ? ' <span class="small muted">· needs a Hugging Face token</span>' : ""}</td>
      <td>${esc((c.languages || []).map((l) => l === "*" ? "Many" : (LANG_NAME[l] || l)).join(", ") || "–")}</td>
      <td class="small">${esc(c.size)}</td><td>${c.installed ? '<span class="inst">Installed</span>' : ""}</td></tr>`).join("");
  } catch (e) { fail(e); }
}
async function downloadPacks() {
  const ids = $$("#catTbl input[data-pack]:checked").map((x) => x.dataset.pack);
  const repo = $("#cRepo").value.trim();
  const custom = repo ? { repo, engine: $("#cEngine").value, languages: $("#cLang").value === "auto" ? "*" : $("#cLang").value } : null;
  if (!ids.length && !custom) { toast("Tick at least one pack, or enter a custom model id.", true); return; }
  try {
    await api("/api/packs/download", { method: "POST", json: { ids, custom, token: $("#hfToken").value, keep: $("#keepPacks").checked } });
    $$("#catTbl input[data-pack]:checked").forEach((x) => (x.checked = false));
    $("#dlMsg").textContent = "Started — follow progress in the queue on the Transcribe tab.";
    toast("Downloading model packs… see the queue on the Transcribe tab.", false, 6000);
    pollJobs();
  } catch (e) { fail(e); }
}
function initPacks() {
  fillSelect($("#cLang"), [["auto", "Many languages (*)"], ...LANGS.filter(([c]) => c !== "auto")], "as");
  $("#dlBtn").addEventListener("click", downloadPacks);
  $("#leSave").addEventListener("click", () => saveLangEngines(false));
  $("#leReset").addEventListener("click", () => saveLangEngines(true));
  $("#packFile").addEventListener("change", async (e) => {
    const f = e.target.files[0]; if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    try { toast(`Uploading ${f.name}… large packs take a while.`, false, 8000); await api("/api/packs/install", { method: "POST", body: fd }); toast("Installing… see the queue on the Transcribe tab."); pollJobs(); }
    catch (err) { fail(err); }
    e.target.value = "";
  });
  $("#packPathBtn").addEventListener("click", async () => {
    try { await api("/api/packs/install-path", { method: "POST", json: { path: $("#packPath").value } }); toast("Installing… see the queue on the Transcribe tab."); pollJobs(); }
    catch (err) { fail(err); }
  });
  $("#packTbl").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-rm]"); if (!b) return;
    if (!confirm(`Remove the pack "${b.dataset.rm}"? You can reinstall it later from its file.`)) return;
    try { await api(`/api/packs/${encodeURIComponent(b.dataset.rm)}`, { method: "DELETE" }); await refreshInfo(); loadPacks(); } catch (err) { fail(err); }
  });
}
async function loadSettings() {
  const s = S.settings = await api("/api/settings");
  $("#sDevice").value = s.device; $("#sCompute").value = s.compute_type; $("#sLang").value = s.default_language;
  $("#sEngine").value = [...$("#sEngine").options].some((o) => o.value === s.default_engine) ? s.default_engine : "auto";
  $("#sBeam").value = s.beam_size; $("#sThreads").value = s.cpu_threads; $("#sSpk").value = s.max_speakers; $("#sTr").value = s.translation_target;
  $("#sVad").checked = s.vad_filter; $("#sWords").checked = s.word_timestamps; $("#sCode").checked = s.code_switching; $("#sGuard").checked = s.hallucination_guard;
  $("#sDenoise").checked = s.denoise; $("#sNorm").checked = s.normalize; $("#sTrim").checked = s.trim_silence; $("#sDiar").checked = s.diarize_default;
  $("#sVocab").value = (s.custom_vocabulary || []).join("\n");
  $("#sRepl").value = (s.replacements || []).map((r) => `${r.from} => ${r.to}`).join("\n");
  const i = S.info || {};
  $("#sPaths").textContent = `Projects and packs are stored in: ${i.data_dir || ""}`;
}
function applyDefaults() {
  const s = S.settings; if (!s) return;
  $$("#optLang, #liveLang").forEach((x) => (x.value = s.default_language || "auto"));
  $$("#optEngine, #liveEngine").forEach((x) => { if ([...x.options].some((o) => o.value === s.default_engine)) x.value = s.default_engine; });
  $("#optDenoise").checked = s.denoise; $("#optNorm").checked = s.normalize; $("#optTrim").checked = s.trim_silence;
  $("#optDiar").checked = s.diarize_default; $("#optSpk").value = s.max_speakers || 0;
  $("#trTarget").value = s.translation_target || "eng_Latn";
}
function initSettings() {
  $("#sSave").addEventListener("click", async () => {
    const lines = (v) => v.split("\n").map((x) => x.trim()).filter(Boolean);
    const data = { device: $("#sDevice").value, compute_type: $("#sCompute").value, default_language: $("#sLang").value, default_engine: $("#sEngine").value,
      beam_size: +$("#sBeam").value || 5, cpu_threads: +$("#sThreads").value || 0, max_speakers: +$("#sSpk").value || 0, translation_target: $("#sTr").value,
      vad_filter: $("#sVad").checked, word_timestamps: $("#sWords").checked, code_switching: $("#sCode").checked, hallucination_guard: $("#sGuard").checked,
      denoise: $("#sDenoise").checked, normalize: $("#sNorm").checked, trim_silence: $("#sTrim").checked, diarize_default: $("#sDiar").checked,
      custom_vocabulary: lines($("#sVocab").value),
      replacements: lines($("#sRepl").value).map((l) => l.split("=>")).filter((p) => p.length === 2).map(([a, b]) => ({ from: a.trim(), to: b.trim() })) };
    try { S.settings = await api("/api/settings", { method: "POST", json: data }); applyDefaults(); await refreshInfo(); $("#sMsg").textContent = "Saved."; setTimeout(() => ($("#sMsg").textContent = ""), 2500); }
    catch (e) { fail(e); }
  });
}

/* ------------------------------------------------------------------ help & about */
let HELP = null;
async function openHelp() {
  openModal("helpModal");
  if (!HELP) HELP = await api("/help.json");
  renderHelp($("#helpSearch").value);
  $("#helpSearch").focus();
}
function renderHelp(q) {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const plain = (h) => h.replace(/<[^>]+>/g, " ").toLowerCase();
  const secs = HELP.filter((s) => !words.length || words.every((w) => (s.title + " " + plain(s.body)).toLowerCase().includes(w)));
  $("#helpToc").innerHTML = secs.map((s) => `<a href="#h-${s.id}" data-h="${s.id}">${esc(s.title)}</a>`).join("");
  $("#helpContent").innerHTML = secs.length ? secs.map((s) => `<section id="h-${s.id}"><h3>${esc(s.title)}</h3>${s.body}</section>`).join("")
    : `<p class="help-empty">Nothing matches “${esc(q)}”. Try another word.</p>`;
  if (words.length) highlight($("#helpContent"), words);
}
function highlight(root, words) {
  const re = new RegExp("(" + words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")", "gi");
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const n of nodes) {
    if (!re.test(n.nodeValue)) continue; re.lastIndex = 0;
    const span = document.createElement("span");
    span.innerHTML = esc(n.nodeValue).replace(re, "<mark>$1</mark>");
    n.parentNode.replaceChild(span, n);
  }
}
function initHelp() {
  $("#helpSearch").addEventListener("input", (e) => renderHelp(e.target.value));
  $("#helpToc").addEventListener("click", (e) => {
    const a = e.target.closest("a"); if (!a) return; e.preventDefault();
    $("#h-" + a.dataset.h).scrollIntoView({ behavior: "smooth", block: "start" });
  });
}
async function openAbout() {
  const i = S.info || (await api("/api/info"));
  $("#aboutName").textContent = i.name; $("#aboutVer").textContent = "Version " + i.version;
  $("#aboutEmail").textContent = i.email; $("#aboutEmail").href = "mailto:" + i.email;
  $("#aboutSources").innerHTML = i.sources.map((s) => `<li><b>${esc(s.name)}</b> — ${esc(s.repo)} (${esc(s.url)}) · ${esc(s.licence)}</li>`).join("");
  $("#aboutComps tbody").innerHTML = i.components.map((c) => `<tr><td>${esc(c.name)}</td><td>${esc(c.licence)}</td></tr>`).join("");
  openModal("aboutModal");
}

/* ------------------------------------------------------------------ editor */
const audioEl = () => $("#audio");
async function openProject(id, seekTo = null, keepView = false) {
  try {
    const P = await api(`/api/projects/${id}`);
    if (!keepView) go("editor");
    S.P = P; S.dirty = false; S.sel = null; S.roman = null;
    $("#edName").value = P.name; $("#edTags").value = (P.tags || []).join(", ");
    $("#edMeta").textContent = `${clock(P.duration)} · ${LANG_NAME[P.language] || P.language || "–"} · ${P.engine || "–"}${P.device ? " · " + P.device.toUpperCase() : ""} · ${P.status}`;
    $("#edNotes").textContent = (P.notes || []).join(" · ");
    $("#burnBtn").classList.toggle("hidden", !P.has_video);
    setDirty(false);
    const a = audioEl();
    const src = `/api/projects/${id}/media?v=${encodeURIComponent(P.updated || "")}`;
    if (!a.src.endsWith(src)) a.src = src;
    a.playbackRate = +$("#pSpeed").value;
    S.peaks = await api(`/api/projects/${id}/peaks`).catch(() => []);
    $("#trInfo").textContent = P.translation ? `Translated to ${(TR_TARGETS.find((t) => t[0] === P.translation.target) || [0, P.translation.target])[1]}.` : "";
    renderTranscript(); renderSpeakers(); drawWave();
    if (seekTo != null) { a.currentTime = seekTo; }
    if (P.status === "processing" || P.status === "queued") toast("This project is still being processed — it will refresh when done.");
  } catch (e) { fail(e); }
}
function setDirty(d) { S.dirty = d; $("#edDirty").classList.toggle("hidden", !d); }
function spkName(k) { return (S.P.speakers || {})[k] || k || ""; }
function spkColor(k) { const keys = Object.keys(S.P.speakers || {}); const i = keys.indexOf(k); return i < 0 ? "var(--muted)" : SPK_COLORS[i % SPK_COLORS.length]; }

function segHTML(s, i) {
  const mode = $("#viewText").value;
  const tr = ((S.P.translation || {}).texts || [])[i];
  let body;
  if (mode === "roman" && S.roman) body = `<div class="txt" data-ro="1">${esc(S.roman[i] || s.text)}</div>`;
  else if (mode === "translation" && tr != null) body = `<div class="txt" data-ro="1">${esc(tr)}</div>`;
  else {
    const words = s.words || [];
    const inner = words.length ? words.map((w, k) => { const c = w.p < 0.5 ? 0 : w.p < 0.7 ? 1 : w.p < 0.85 ? 2 : 3;
      return `<span class="w c${c}" data-k="${k}" title="${(w.p * 100).toFixed(0)}% · ${clock(w.s)}">${esc(w.w)}</span>`; }).join("") : esc(s.text);
    body = `<div class="txt" contenteditable="true" spellcheck="false">${inner}</div>`;
    if (mode === "both" && tr != null) body += `<div class="tr">${esc(tr)}</div>`;
  }
  const opts = [["", "—"], ...Object.keys(S.P.speakers || {}).map((k) => [k, spkName(k)])];
  return `<div class="seg" data-i="${i}">
    <div class="time" title="Play from here">${clockMs(s.start)}</div>
    <select class="spk" style="color:${spkColor(s.speaker)}">${opts.map(([v, l]) => `<option value="${esc(v)}" ${v === (s.speaker || "") ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>
    ${body}
    <div class="acts"><button data-a="split" title="Split at cursor (Ctrl+Enter)">✂</button><button data-a="merge" title="Merge with next">⤓</button><button data-a="del" title="Delete segment">🗑</button></div>
  </div>`;
}
function renderTranscript() {
  const el = $("#txList");
  el.classList.toggle("heat", $("#heatToggle").checked);
  el.innerHTML = S.P.segments.length ? S.P.segments.map(segHTML).join("") : '<p class="muted">No speech found yet.</p>';
  applyFind();
}
function rowOf(i) { return $(`#txList .seg[data-i="${i}"]`); }

function commitText(row) {
  const i = +row.dataset.i, s = S.P.segments[i], txt = $(".txt", row);
  if (!txt || txt.dataset.ro) return;
  const text = txt.textContent.replace(/\s+/g, " ").trim();
  if (text === s.text.trim()) return;
  s.text = text;
  s.words = redistribute(text, s.start, s.end);
  setDirty(true);
}
function redistribute(text, start, end) {
  const toks = text.split(/(?=\s)/).filter((t) => t.trim());
  const total = toks.reduce((a, t) => a + t.trim().length, 0) || 1;
  let t = start;
  return toks.map((w) => { const d = (end - start) * (w.trim().length / total); const o = { w: (w.startsWith(" ") ? w : " " + w), s: +t.toFixed(3), e: +(t + d).toFixed(3), p: 1 }; t += d; return o; });
}
function splitSeg(i, caretOffset) {
  const s = S.P.segments[i];
  const text = s.text;
  let cut = caretOffset ?? Math.floor(text.length / 2);
  cut = Math.max(1, Math.min(text.length - 1, cut));
  const a = text.slice(0, cut).trim(), b = text.slice(cut).trim();
  if (!a || !b) return;
  const ws = s.words || [];
  let at = s.start + (s.end - s.start) * (cut / text.length);
  if (ws.length) { let n = 0; for (const w of ws) { n += w.w.length; if (n >= cut + 1) { at = w.e; break; } } }
  const w1 = ws.filter((w) => w.e <= at + 1e-3), w2 = ws.filter((w) => w.e > at + 1e-3);
  const s1 = { ...s, text: a, end: at, words: w1.length ? w1 : redistribute(a, s.start, at) };
  const s2 = { ...s, text: b, start: at, words: w2.length ? w2 : redistribute(b, at, s.end) };
  S.P.segments.splice(i, 1, s1, s2);
  renumber(); setDirty(true); renderTranscript(); drawWave();
}
function mergeSeg(i) {
  const a = S.P.segments[i], b = S.P.segments[i + 1]; if (!b) return;
  S.P.segments.splice(i, 2, { ...a, text: (a.text + " " + b.text).trim(), end: b.end, words: [...(a.words || []), ...(b.words || [])],
    conf: +(((a.conf || 1) + (b.conf || 1)) / 2).toFixed(3) });
  renumber(); setDirty(true); renderTranscript(); drawWave();
}
function renumber() { S.P.segments.forEach((s, i) => (s.id = i)); if (S.P.translation) S.P.translation.stale = true; }
function caretOffsetIn(el) {
  const sel = window.getSelection(); if (!sel.rangeCount) return null;
  const r = sel.getRangeAt(0); if (!el.contains(r.startContainer)) return null;
  const pre = r.cloneRange(); pre.selectNodeContents(el); pre.setEnd(r.startContainer, r.startOffset);
  return pre.toString().length;
}
function selectSeg(i, scroll = false) {
  S.sel = i;
  $$("#txList .seg.sel").forEach((r) => r.classList.remove("sel"));
  const r = rowOf(i); if (r) { r.classList.add("sel"); if (scroll) r.scrollIntoView({ block: "center", behavior: "smooth" }); }
  drawWave();
}
function seek(t, play = true) { const a = audioEl(); a.currentTime = Math.max(0, t); if (play) a.play().catch(() => {}); }

function initEditor() {
  const list = $("#txList");
  list.addEventListener("click", (e) => {
    const row = e.target.closest(".seg"); if (!row) return;
    const i = +row.dataset.i, s = S.P.segments[i];
    if (e.target.classList.contains("time")) { selectSeg(i); seek(s.start); return; }
    if (e.target.classList.contains("w") && !e.ctrlKey && document.activeElement !== e.target.closest(".txt")) { selectSeg(i); seek(s.words[+e.target.dataset.k].s); return; }
    const act = e.target.closest("[data-a]");
    if (act) {
      commitText(row);
      if (act.dataset.a === "split") splitSeg(i, caretOffsetIn($(".txt", row)));
      if (act.dataset.a === "merge") mergeSeg(i);
      if (act.dataset.a === "del" && confirm("Delete this segment?")) { S.P.segments.splice(i, 1); renumber(); setDirty(true); renderTranscript(); drawWave(); }
      return;
    }
    selectSeg(i);
  });
  list.addEventListener("dblclick", (e) => { const w = e.target.closest(".w"); if (w) { const row = w.closest(".seg"); seek(S.P.segments[+row.dataset.i].words[+w.dataset.k].s); } });
  list.addEventListener("input", (e) => { if (e.target.closest(".txt")) setDirty(true); });
  list.addEventListener("focusout", (e) => { const row = e.target.closest(".seg"); if (row && e.target.classList.contains("txt")) { commitText(row); } });
  list.addEventListener("change", (e) => {
    if (!e.target.classList.contains("spk")) return;
    const i = +e.target.closest(".seg").dataset.i; S.P.segments[i].speaker = e.target.value || null;
    e.target.style.color = spkColor(e.target.value); setDirty(true); renderSpeakers();
  });
  list.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.key === "Enter") { e.preventDefault(); const row = e.target.closest(".seg"); if (row) { const off = caretOffsetIn($(".txt", row)); commitText(row); splitSeg(+row.dataset.i, off); } }
  });
  $("#edName").addEventListener("input", () => setDirty(true));
  $("#edTags").addEventListener("input", () => setDirty(true));
  $("#edBack").addEventListener("click", () => go("home"));
  $("#edSave").addEventListener("click", saveProject);
  $("#viewText").addEventListener("change", async () => {
    if ($("#viewText").value === "roman" && !S.roman) {
      try { S.roman = (await api("/api/romanize", { method: "POST", json: { lang: S.P.language, texts: S.P.segments.map((s) => s.text) } })).texts; } catch (e) { fail(e); }
    }
    if (["translation", "both"].includes($("#viewText").value) && !S.P.translation) toast("No translation yet — use Translate on the right.");
    renderTranscript();
  });
  $("#heatToggle").addEventListener("change", () => $("#txList").classList.toggle("heat", $("#heatToggle").checked));
  $("#findBox").addEventListener("input", applyFind);
  $("#replAll").addEventListener("click", replaceAll);
  // history
  $("#edVerBtn").addEventListener("click", async () => {
    const vs = await api(`/api/projects/${S.P.id}/versions`);
    $("#edVerMenu").innerHTML = vs.length ? vs.map((v) => `<button data-v="${v}">${v.replace(/^(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)(\d\d)$/, "$3/$2/$1 $4:$5:$6")}</button>`).join("") : '<div class="muted small" style="padding:8px">No earlier versions yet.</div>';
  });
  $("#edVerMenu").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-v]"); if (!b) return;
    if (!confirm("Restore this version? Your current text is kept in History.")) return;
    await api(`/api/projects/${S.P.id}/restore`, { method: "POST", json: { version: b.dataset.v } }); openProject(S.P.id, null, true); toast("Version restored.");
  });
  // export
  $("#edExportMenu").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-fmt]"); if (!b) return;
    if (S.dirty) await saveProject();
    const text = $("#exText").value, sp = $("#exSpk").checked ? 1 : 0, ts = $("#exTs").checked ? 1 : 0;
    if (b.dataset.fmt === "burn") {
      $("#edExportMenu").classList.remove("open");
      try { await burnSubtitles(text, sp); } catch (err) { fail(err); }
      return;
    }
    window.location.href = `/api/projects/${S.P.id}/export?fmt=${b.dataset.fmt}&text=${text}&speakers=${sp}&timestamps=${ts}`;
    $("#edExportMenu").classList.remove("open");
  });
  // speakers
  $("#spkList").addEventListener("input", (e) => { const k = e.target.dataset.k; if (k) { S.P.speakers[k] = e.target.value; setDirty(true); refreshSpeakerChips(); } });
  $("#addSpk").addEventListener("click", () => { const keys = Object.keys(S.P.speakers || {}); let n = keys.length + 1; while (S.P.speakers["S" + n]) n++; S.P.speakers = { ...(S.P.speakers || {}), ["S" + n]: "Speaker " + n }; setDirty(true); renderSpeakers(); renderTranscript(); });
  $("#reDiar").addEventListener("click", async () => {
    if (!S.info.diarization) { toast("Install the speaker diarization pack first (Model packs).", true); return; }
    if (S.dirty) await saveProject();
    try { await api(`/api/projects/${S.P.id}/diarize`, { method: "POST", json: { max_speakers: +$("#optSpk").value || 0 } }); toast("Finding speakers…"); pollJobs(); } catch (e) { fail(e); }
  });
  $("#trBtn").addEventListener("click", async () => {
    if (S.dirty) await saveProject();
    try { await api(`/api/projects/${S.P.id}/translate`, { method: "POST", json: { target: $("#trTarget").value, source: S.P.language } }); toast("Translating…"); pollJobs(); } catch (e) { fail(e); }
  });
  $("#reBtn").addEventListener("click", async () => {
    if (S.dirty && !confirm("Re-running replaces the text (your current version is kept in History). Continue?")) return;
    try { await api(`/api/projects/${S.P.id}/transcribe`, { method: "POST", json: { language: $("#reLang").value, engine: $("#reEngine").value, diarize: Object.keys(S.P.speakers || {}).length > 0 } }); toast("Transcribing again…"); pollJobs(); } catch (e) { fail(e); }
  });
  // player
  const a = audioEl();
  $("#pPlay").addEventListener("click", () => (a.paused ? a.play() : a.pause()));
  $("#pBack").addEventListener("click", () => seek(a.currentTime - 5, false));
  $("#pFwd").addEventListener("click", () => seek(a.currentTime + 5, false));
  $("#pSpeed").addEventListener("change", () => (a.playbackRate = +$("#pSpeed").value));
  $("#pZoom").addEventListener("input", drawWave);
  a.addEventListener("play", () => ($("#pPlay").textContent = "⏸ Pause"));
  a.addEventListener("pause", () => ($("#pPlay").textContent = "▶ Play"));
  a.addEventListener("loadedmetadata", drawWave);
  document.addEventListener("keydown", (e) => {
    if (S.view !== "editor") return;
    if (e.ctrlKey && (e.key === "s" || e.key === "S")) { e.preventDefault(); saveProject(); }
    else if (e.ctrlKey && e.code === "Space") { e.preventDefault(); a.paused ? a.play() : a.pause(); }
    else if (e.altKey && e.key === "ArrowLeft") { e.preventDefault(); seek(a.currentTime - 5, false); }
    else if (e.altKey && e.key === "ArrowRight") { e.preventDefault(); seek(a.currentTime + 5, false); }
    else if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
      e.preventDefault(); const n = S.P.segments.length; if (!n) return;
      const cur = S.sel ?? currentSegIndex(a.currentTime) ?? 0; const i = Math.max(0, Math.min(n - 1, cur + (e.key === "ArrowUp" ? -1 : 1)));
      selectSeg(i, true); seek(S.P.segments[i].start, !a.paused);
    } else if (e.altKey && (e.key === "[" || e.key === "]")) {
      e.preventDefault(); const opts = [...$("#pSpeed").options].map((o) => o.value); let k = opts.indexOf($("#pSpeed").value);
      k = Math.max(0, Math.min(opts.length - 1, k + (e.key === "]" ? 1 : -1))); $("#pSpeed").value = opts[k]; a.playbackRate = +opts[k];
    }
  });
  initWave();
  requestAnimationFrame(tickPlayhead);
}
/* Subtitles are drawn by the browser (correct Indic shaping), then overlaid on the video by FFmpeg. */
function cueText(i, mode, withSpk) {
  const s = S.P.segments[i], tr = ((S.P.translation || {}).texts || [])[i];
  let t = s.text;
  if (mode === "translation" && tr != null) t = tr; else if (mode === "both" && tr != null) t = s.text + "\n" + tr;
  if (withSpk && s.speaker) t = spkName(s.speaker) + ": " + t;
  return t;
}
function wrapLines(g, text, maxW) {
  const out = [];
  for (const para of text.split("\n")) {
    let line = "";
    for (const w of para.split(/\s+/).filter(Boolean)) {
      const test = line ? line + " " + w : w;
      if (line && g.measureText(test).width > maxW) { out.push(line); line = w; } else line = test;
    }
    out.push(line);
  }
  return out;
}
function renderCue(text, W, H) {
  const fs = Math.max(16, Math.round(H / 18)), lh = Math.round(fs * 1.35);
  const c = document.createElement("canvas"); const g = c.getContext("2d");
  g.font = `600 ${fs}px "Segoe UI", "VTS Noto Bengali", "VTS Noto Devanagari", "Nirmala UI", sans-serif`;
  const lines = wrapLines(g, text, W * 0.88);
  c.width = W; c.height = lines.length * lh + Math.round(H / 14);
  g.font = `600 ${fs}px "Segoe UI", "VTS Noto Bengali", "VTS Noto Devanagari", "Nirmala UI", sans-serif`;
  g.textAlign = "center"; g.textBaseline = "top"; g.lineJoin = "round";
  g.lineWidth = Math.max(3, fs / 7); g.strokeStyle = "rgba(0,0,0,.9)"; g.fillStyle = "#fff";
  lines.forEach((l, k) => { g.strokeText(l, W / 2, k * lh); g.fillText(l, W / 2, k * lh); });
  return new Promise((res) => c.toBlob(res, "image/png"));
}
async function burnSubtitles(mode, withSpk) {
  const { width, height } = await api(`/api/projects/${S.P.id}/videoinfo`);
  await Promise.all(["VTS Noto Bengali", "VTS Noto Devanagari"].flatMap((f) => [document.fonts.load(`600 20px "${f}"`, "অক"), document.fonts.load(`600 20px "${f}"`, "कक")])).catch(() => {});
  toast("Preparing subtitles…");
  const fd = new FormData(), cues = [];
  for (let i = 0; i < S.P.segments.length; i++) {
    const s = S.P.segments[i], text = cueText(i, mode, !!withSpk).trim();
    if (!text) continue;
    fd.append("cue" + cues.length, await renderCue(text, width, height), `cue${cues.length}.png`);
    cues.push({ start: s.start, end: s.end });
  }
  fd.append("cues", JSON.stringify(cues));
  await api(`/api/projects/${S.P.id}/burn`, { method: "POST", body: fd });
  toast("Burning subtitles into the video… it downloads when ready.", false, 6000);
  pollJobs();
}
function refreshSpeakerChips() { $$("#txList .spk").forEach((sel) => [...sel.options].forEach((o) => { if (o.value) o.textContent = spkName(o.value); })); renderStats(); }
function renderSpeakers() {
  const sp = S.P.speakers || {};
  $("#spkList").innerHTML = Object.keys(sp).length ? Object.keys(sp).map((k) => `<div class="spk-row"><span class="dot" style="background:${spkColor(k)}"></span><input data-k="${k}" value="${esc(sp[k])}" aria-label="Name for ${k}"></div>`).join("")
    : '<p class="muted small">No speakers yet. Tick “Identify speakers” when transcribing, use “Find speakers again”, or add them by hand.</p>';
  renderStats();
}
function renderStats() {
  const t = {}; let total = 0;
  for (const s of S.P.segments) { const k = s.speaker || ""; const d = Math.max(0, s.end - s.start); t[k] = (t[k] || 0) + d; total += d; }
  const turns = {}; let prev = null; for (const s of S.P.segments) { if (s.speaker !== prev) turns[s.speaker || ""] = (turns[s.speaker || ""] || 0) + 1; prev = s.speaker; }
  $("#spkStats").innerHTML = Object.keys(t).filter((k) => k).map((k) => `<div class="stat">${esc(spkName(k))} — ${clock(t[k])} (${Math.round((t[k] / (total || 1)) * 100)}%), ${turns[k] || 0} turns
    <div class="bar" style="width:${Math.max(2, (t[k] / (total || 1)) * 100)}%;background:${spkColor(k)}"></div></div>`).join("") || '<p class="muted small">—</p>';
}
async function saveProject() {
  if (!S.P) return;
  const active = document.activeElement && document.activeElement.closest && document.activeElement.closest(".seg");
  if (active) commitText(active);
  try {
    const body = { name: $("#edName").value.trim() || S.P.name, tags: $("#edTags").value.split(",").map((x) => x.trim()).filter(Boolean),
      segments: S.P.segments, speakers: S.P.speakers || {} };
    if (S.P.translation && S.P.translation.stale) body.translation = null;
    const P = await api(`/api/projects/${S.P.id}`, { method: "PUT", json: body });
    S.P.updated = P.updated; S.P.name = P.name; S.P.translation = P.translation; setDirty(false); toast("Saved.");
  } catch (e) { fail(e); }
}
function applyFind() {
  const q = $("#findBox").value.trim();
  $$("#txList mark.find").forEach((m) => m.replaceWith(document.createTextNode(m.textContent)));
  $$("#txList .txt").forEach((t) => t.normalize());
  if (!q) { $("#findCount").textContent = ""; return; }
  let n = 0;
  const re = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
  for (const t of $$("#txList .txt")) {
    const walker = document.createTreeWalker(t, NodeFilter.SHOW_TEXT); const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const v = node.nodeValue; re.lastIndex = 0; if (!re.test(v)) continue; re.lastIndex = 0;
      const frag = document.createDocumentFragment(); let last = 0, m;
      while ((m = re.exec(v))) { frag.append(v.slice(last, m.index)); const mk = document.createElement("mark"); mk.className = "find"; mk.textContent = m[0]; frag.append(mk); last = m.index + m[0].length; n++; }
      frag.append(v.slice(last)); node.replaceWith(frag);
    }
  }
  $("#findCount").textContent = n ? `${n} found` : "not found";
}
function replaceAll() {
  const q = $("#findBox").value.trim(); if (!q) return;
  const re = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi"); let n = 0;
  S.P.segments.forEach((s) => { const nt = s.text.replace(re, () => { n++; return $("#replBox").value; }); if (nt !== s.text) { s.text = nt; s.words = redistribute(nt, s.start, s.end); } });
  if (n) { setDirty(true); renderTranscript(); toast(`Replaced ${n} occurrence(s).`); } else toast("Nothing to replace.");
}

/* ---- waveform with selectable segment and draggable edges */
const W = { drag: null, view: [0, 1] };
function duration() { const a = audioEl(); return (a.duration && isFinite(a.duration)) ? a.duration : (S.P ? S.P.duration || 1 : 1); }
function waveWindow() {
  const d = duration(), z = +$("#pZoom").value, span = d / z, t = audioEl().currentTime;
  let start = W.view[0];
  if (z === 1) start = 0;
  else if ($("#pFollow").checked && !audioEl().paused) start = t - span * 0.3;
  else if (t < start || t > start + span) start = t - span * 0.3;
  start = Math.max(0, Math.min(d - span, start));
  W.view = [start, start + span];
  return W.view;
}
function drawWave() {
  const c = $("#wave"); if (!c || !S.P) return;
  const dpr = window.devicePixelRatio || 1, w = c.clientWidth, h = c.clientHeight;
  if (!w) return;
  c.width = w * dpr; c.height = h * dpr;
  const g = c.getContext("2d"); g.scale(dpr, dpr); g.clearRect(0, 0, w, h);
  const css = getComputedStyle(document.documentElement);
  const col = (n) => css.getPropertyValue(n).trim();
  const d = duration(), [v0, v1] = waveWindow(), X = (t) => ((t - v0) / (v1 - v0)) * w;
  // segments
  S.P.segments.forEach((s, i) => {
    if (s.end < v0 || s.start > v1) return;
    g.fillStyle = i === S.sel ? col("--play") : (i % 2 ? "rgba(127,127,127,.08)" : "rgba(127,127,127,.15)");
    g.fillRect(X(s.start), 0, Math.max(1, X(s.end) - X(s.start)), h);
  });
  // peaks
  const P = S.peaks, n = P.length / 2;
  if (n) {
    g.fillStyle = col("--accent"); const mid = h / 2;
    for (let x = 0; x < w; x++) {
      const t0 = v0 + (x / w) * (v1 - v0), t1 = v0 + ((x + 1) / w) * (v1 - v0);
      const a = Math.floor((t0 / d) * n), b = Math.max(a + 1, Math.floor((t1 / d) * n));
      let mn = 0, mx = 0; for (let k = a; k < b && k < n; k++) { mn = Math.min(mn, P[2 * k]); mx = Math.max(mx, P[2 * k + 1]); }
      g.fillRect(x, mid - mx * mid * 0.95, 1, Math.max(1, (mx - mn) * mid * 0.95));
    }
  }
  // selected segment edges
  if (S.sel != null && S.P.segments[S.sel]) {
    const s = S.P.segments[S.sel]; g.fillStyle = col("--text");
    for (const t of [s.start, s.end]) { const x = X(t); g.fillRect(x - 1, 0, 2, h); g.fillRect(x - 4, h / 2 - 10, 8, 20); }
  }
  // playhead
  const px = X(audioEl().currentTime); g.fillStyle = col("--danger"); g.fillRect(px - 1, 0, 2, h);
}
function initWave() {
  const c = $("#wave");
  const tAt = (e) => { const r = c.getBoundingClientRect(); return W.view[0] + ((e.clientX - r.left) / r.width) * (W.view[1] - W.view[0]); };
  const xOf = (t) => ((t - W.view[0]) / (W.view[1] - W.view[0])) * c.clientWidth;
  c.addEventListener("mousedown", (e) => {
    const t = tAt(e), r = c.getBoundingClientRect(), x = e.clientX - r.left;
    if (S.sel != null) { const s = S.P.segments[S.sel];
      if (Math.abs(xOf(s.start) - x) < 7) { W.drag = "start"; return; }
      if (Math.abs(xOf(s.end) - x) < 7) { W.drag = "end"; return; } }
    const i = S.P.segments.findIndex((s) => t >= s.start && t <= s.end);
    if (i >= 0) selectSeg(i, true);
    seek(t, false); drawWave();
  });
  window.addEventListener("mousemove", (e) => {
    if (!W.drag || S.sel == null) return;
    const s = S.P.segments[S.sel], prev = S.P.segments[S.sel - 1], next = S.P.segments[S.sel + 1];
    let t = +tAt(e).toFixed(2);
    if (W.drag === "start") s.start = Math.max(prev ? prev.end : 0, Math.min(t, s.end - 0.05));
    else s.end = Math.min(next ? next.start : duration(), Math.max(t, s.start + 0.05));
    const row = rowOf(S.sel); if (row) $(".time", row).textContent = clockMs(s.start);
    setDirty(true); drawWave();
  });
  window.addEventListener("mouseup", () => { W.drag = null; });
  c.addEventListener("wheel", (e) => { if (+$("#pZoom").value > 1) { e.preventDefault(); const span = W.view[1] - W.view[0]; const a = audioEl(); a.currentTime = Math.max(0, Math.min(duration(), a.currentTime + (e.deltaY > 0 ? 1 : -1) * span * 0.1)); drawWave(); } }, { passive: false });
  window.addEventListener("resize", drawWave);
}
function currentSegIndex(t) { const segs = S.P ? S.P.segments : []; for (let i = 0; i < segs.length; i++) if (t >= segs[i].start && t < segs[i].end) return i; return null; }
let lastSeg = null, lastWord = null;
function tickPlayhead() {
  requestAnimationFrame(tickPlayhead);
  if (S.view !== "editor" || !S.P) return;
  const a = audioEl(), t = a.currentTime;
  $("#pTime").textContent = `${clock(t)} / ${clock(duration())}`;
  if (!a.paused || W.drag) drawWave();
  const i = currentSegIndex(t);
  if (i !== lastSeg) {
    if (lastSeg != null && rowOf(lastSeg)) rowOf(lastSeg).classList.remove("cur");
    if (i != null && rowOf(i)) { const r = rowOf(i); r.classList.add("cur");
      if ($("#pFollow").checked && !a.paused && !(document.activeElement && document.activeElement.isContentEditable)) r.scrollIntoView({ block: "center", behavior: "smooth" }); }
    lastSeg = i;
  }
  if (lastWord) lastWord.classList.remove("now");
  lastWord = null;
  if (i != null) { const ws = S.P.segments[i].words || []; const k = ws.findIndex((w) => t >= w.s && t < w.e);
    if (k >= 0) { const el = rowOf(i) && $(`.w[data-k="${k}"]`, rowOf(i)); if (el) { el.classList.add("now"); lastWord = el; } } }
}

/* ------------------------------------------------------------------ live microphone */
const L = { ws: null, ctx: null, stream: null, node: null, ready: false, t0: 0 };
function initLive() {
  $("#liveBtn").addEventListener("click", () => (L.ws ? stopLive() : startLive()));
  $("#liveOut").addEventListener("click", (e) => { const b = e.target.closest("[data-open]"); if (b) openProject(b.dataset.open); });
}
async function startLive() {
  if (!S.info.asr_packs.length) { toast("Install a speech model pack first (Model packs).", true); return; }
  try {
    L.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  } catch (e) { toast("Microphone not available or permission denied: " + e.message, true, 6000); return; }
  L.ctx = new AudioContext();
  await L.ctx.audioWorklet.addModule("/assets/pcm-worklet.js");
  const src = L.ctx.createMediaStreamSource(L.stream);
  L.node = new AudioWorkletNode(L.ctx, "pcm-worklet");
  src.connect(L.node);
  L.ready = false;
  L.ws = new WebSocket(`ws://${location.host}/api/live`);
  L.ws.binaryType = "arraybuffer";
  L.ws.onopen = () => L.ws.send(JSON.stringify({ type: "start", language: $("#liveLang").value, engine: $("#liveEngine").value, name: $("#liveName").value.trim() }));
  L.ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "ready") { L.ready = true; $("#liveStatus").textContent = "Listening…"; }
    else if (m.type === "partial") $("#livePartial").textContent = m.text;
    else if (m.type === "final") {
      $("#livePartial").textContent = "";
      const d = document.createElement("div"); d.innerHTML = `<span class="t">${clock(m.segment.start)}</span>${esc(m.segment.text)}`;
      $("#liveOut").append(d); $("#liveOut").scrollTop = 1e9;
    } else if (m.type === "saved") {
      $("#liveStatus").textContent = "";
      if (m.project_id) { const d = document.createElement("div"); d.innerHTML = `Saved as a project. <button class="btn small primary" data-open="${m.project_id}">Open in editor</button>`; $("#liveOut").append(d); }
      cleanupLive();
    } else if (m.type === "error") { toast(m.message, true, 6000); }
  };
  L.ws.onclose = () => cleanupLive();
  L.node.port.onmessage = (ev) => {
    $("#liveMeter").style.width = Math.min(100, ev.data.peak * 140) + "%";
    if (L.ws && L.ready && L.ws.readyState === 1) L.ws.send(ev.data.pcm);
  };
  $("#liveBtn").textContent = "■ Stop"; $("#liveBtn").classList.replace("primary", "danger");
  $("#liveOut").innerHTML = ""; $("#liveStatus").textContent = "Starting…";
}
function stopLive() {
  if (L.ws && L.ws.readyState === 1) { L.ws.send(JSON.stringify({ type: "stop" })); $("#liveStatus").textContent = "Finishing and saving…"; }
  if (L.stream) L.stream.getTracks().forEach((t) => t.stop());
  if (L.node) L.node.port.onmessage = null;
  $("#liveBtn").disabled = true;
}
function cleanupLive() {
  if (L.stream) L.stream.getTracks().forEach((t) => t.stop());
  if (L.ctx) L.ctx.close().catch(() => {});
  if (L.ws && L.ws.readyState <= 1) try { L.ws.close(); } catch (e) { /* ignore */ }
  Object.assign(L, { ws: null, ctx: null, stream: null, node: null, ready: false });
  $("#liveBtn").disabled = false; $("#liveBtn").textContent = "● Start"; $("#liveBtn").classList.replace("danger", "primary");
  $("#liveMeter").style.width = "0";
}

/* ------------------------------------------------------------------ boot */
(async function boot() {
  initSplash(); initChrome(); initSelects(); initHome(); initProjects(); initPacks(); initSettings(); initHelp(); initEditor(); initLive();
  try {
    await refreshInfo();
    S.settings = await api("/api/settings");
    applyDefaults();
  } catch (e) { fail(e); }
  loadRecent(); pollJobs();
})();
