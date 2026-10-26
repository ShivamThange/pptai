/* PPTAI Studio — pipeline runner UI (vanilla JS, no build step). */
'use strict';

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};

const state = {
  formats: null, config: null,
  docs: new Map(),      // document_id -> {view, status, parseJobId, findings[]}
  jobs: new Map(),      // job_id -> {row, es, poll, terminal}
  decks: [],
  selectedDeck: null,
  uploading: false,
};

/* ---------------- API helper ---------------- */
async function api(url, options = {}) {
  const response = await fetch(url, options);
  let data = null;
  try { data = await response.json(); } catch { /* non-JSON error body */ }
  if (!response.ok) {
    const detail = data && data.detail;
    const message = detail && (detail.message || (typeof detail === 'string' ? detail : JSON.stringify(detail)));
    const error = new Error(message || `Request failed (${response.status})`);
    error.code = detail && detail.code;
    error.status = response.status;
    throw error;
  }
  return data;
}
const jsonBody = (payload) => ({
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload),
});

/* ---------------- toasts ---------------- */
function toast(message, kind = 'error') {
  const node = el('div', `toast ${kind}`, message);
  $('toast-root').append(node);
  setTimeout(() => { node.style.opacity = '0'; node.style.transition = 'opacity .3s'; }, 5200);
  setTimeout(() => node.remove(), 5600);
}

/* ---------------- worker / config ---------------- */
async function pollWorker() {
  try {
    const status = await api('/api/worker/status');
    const pill = $('worker-pill');
    pill.className = `pill state-${status.state}`;
    const labels = { alive: 'worker online', busy: 'worker busy', stale: 'worker stale — restart it', offline: 'worker offline' };
    $('worker-state').textContent = labels[status.state] || status.state;
    pill.title = status.age_seconds !== null ? `heartbeat ${status.age_seconds}s ago (pid ${status.pid ?? '?'})` : 'no heartbeat yet';
  } catch { /* transient */ }
}

async function loadConfig() {
  try {
    state.config = await api('/api/config');
    const chip = $('model-chip');
    chip.textContent = `${state.config.provider} · ${state.config.model} · ${state.config.max_calls_per_minute}/min · out ${state.config.max_output_tokens} tok`;
    chip.title = `strict coverage: ${state.config.strict_section_coverage ? 'on' : 'off'} · concurrency ${state.config.max_concurrency}`;
    chip.classList.toggle('nokey', !state.config.api_key_present);
    if (!state.config.api_key_present) chip.title += ' · API key missing';
    populateThemes();
  } catch (error) { $('model-chip').textContent = 'config unavailable'; }
}

function populateThemes() {
  const select = $('theme');
  if (!select || !state.config || !state.config.themes) return;
  const current = select.value || 'auto';
  const lensMap = state.config.lens_theme_map || {};
  const options = ['<option value="auto">Auto — follows the lens</option>'];
  for (const [id, theme] of Object.entries(state.config.themes)) {
    const auto = lensMap[$('lens').value] === id ? ' · default for this lens' : '';
    options.push(`<option value="${id}">${theme.name}${auto} — ${theme.description}</option>`);
  }
  select.innerHTML = options.join('');
  select.value = [...select.options].some(o => o.value === current) ? current : 'auto';
}

async function loadFormats() {
  try {
    state.formats = await api('/api/input-formats');
    const ok = state.formats.formats.filter(f => f.adapter_available).map(f => f.type);
    $('formats-hint').textContent = ok.length ? `supported: ${ok.join(', ')}` : 'no format adapters installed';
    const accept = state.formats.formats.flatMap(f => f.extensions).join(',');
    $('file-input').accept = accept;
  } catch { $('formats-hint').textContent = 'format check failed'; }
}

/* ---------------- upload + parse ---------------- */
function extLabel(filename) {
  const ext = (filename.split('.').pop() || '').toLowerCase();
  return ext.slice(0, 4) || 'doc';
}
function fmtBytes(n) {
  if (n > 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
  if (n > 1024) return (n / 1024).toFixed(0) + ' KB';
  return n + ' B';
}

function renderDoc(entry) {
  const row = entry.row;
  row.replaceChildren();
  const thumb = el('div', 'thumb', extLabel(entry.view.filename));
  const meta = el('div', 'meta');
  meta.append(el('div', 'name', entry.view.filename));
  const sub = el('div', 'sub');
  const detected = entry.view.upload && entry.view.upload.detected_type;
  sub.append(`uploaded · ${fmtBytes(entry.view.size_bytes)}`);
  if (detected) sub.append(' · type ', el('code', undefined, detected));
  meta.append(sub);
  const actions = el('div', 'actions');
  const tag = el('span', `status-tag ${entry.status}`, entry.status);
  actions.append(tag);
  row.append(thumb, meta, actions);
  if (entry.findings && entry.findings.length) {
    const note = el('div', 'doc-findings', entry.findings.join(' · '));
    row.append(note);
  }
  updateGenerateButton();
}

async function uploadFiles(files) {
  for (const file of files) {
    await uploadOne(file);
  }
}

async function uploadOne(file) {
  const form = new FormData();
  form.append('file', file);
  form.append('selected_type', 'auto');
  let view;
  try {
    view = await api('/api/documents', { method: 'POST', body: form });
  } catch (error) {
    toast(`Upload failed: ${error.message}`, 'error');
    return;
  }
  const entry = { view, status: 'parsing', parseJobId: null, findings: [], row: el('li', 'doc') };
  state.docs.set(view.id, entry);
  $('doc-list').prepend(entry.row);
  renderDoc(entry);
  try {
    const submitted = await api(`/api/documents/${view.id}/parse`, { method: 'POST', ...jsonBody({}) });
    entry.parseJobId = submitted.job_id;
    followJob(submitted, { kindLabel: 'parse', docId: view.id });
  } catch (error) {
    entry.status = 'failed';
    entry.findings.push(error.message);
    renderDoc(entry);
    toast(`Parse submission failed: ${error.message}`);
  }
}

function onParseUpdate(docId, job) {
  const entry = state.docs.get(docId);
  if (!entry) return;
  if (job.status === 'completed') {
    entry.status = 'parsed';
    const outcome = job.result && job.result.parse_result;
    if (outcome && outcome.findings) {
      entry.findings = outcome.findings.filter(f => f.severity === 'warning' || f.severity === 'error').map(f => f.message).slice(0, 2);
    }
  } else if (job.status === 'failed') {
    entry.status = 'failed';
    entry.findings.push((job.error && job.error.message) || 'parse failed');
  } else if (job.status === 'cancelled') {
    entry.status = 'failed';
    entry.findings.push('parse cancelled');
  }
  renderDoc(entry);
}

function parsedDocs() {
  return [...state.docs.values()].filter(d => d.status === 'parsed');
}

function updateGenerateButton() {
  const count = parsedDocs().length;
  const ready = count > 0;
  $('generate').disabled = !ready || state.uploading;
  if ($('resume-generate')) $('resume-generate').disabled = !ready || state.uploading;
  $('generate-sub').textContent = ready
    ? `${count} parsed source${count > 1 ? 's' : ''} ready`
    : 'upload and parse a source first';
  if ($('resume-sub')) {
    $('resume-sub').textContent = ready ? 'reuse cache / checkpoints' : 'upload a source first';
  }
}

/* ---------------- generation ---------------- */
function collectGenerationPayload(overrides = {}) {
  const sources = parsedDocs().map(d => ({ document_id: d.view.id }));
  const payload = {
    sources,
    lens: $('lens').value,
    extraction_mode: $('extraction_mode').value,
    polish: $('polish').value,
    renderer: $('renderer').value,
    asset_options: $('asset_understanding').value === 'structured'
      ? { mode: 'structured', semantic_understanding: 'auto' }
      : { mode: 'legacy', semantic_understanding: 'off' },
    min_slides: Math.max(1, +$('min_slides').value || 5),
    max_slides: Math.max(1, +$('max_slides').value || 10),
    max_repairs_per_slide: Math.max(0, +$('max_repairs_per_slide').value || 0),
    max_concurrency: Math.max(1, +$('max_concurrency').value || 2),
    theme: $('theme').value || 'auto',
    dynamic_layout: $('dynamic_layout').checked,
    deep_verification: $('deep_verification').checked,
    instruction: $('instruction').value.trim(),
    resume: Boolean($('resume_cache') && $('resume_cache').checked),
    ...overrides,
  };
  if (payload.min_slides > payload.max_slides) [payload.min_slides, payload.max_slides] = [payload.max_slides, payload.min_slides];
  return payload;
}

async function generate(options = {}) {
  const payload = collectGenerationPayload(options);
  if (!payload.sources.length) return;
  try {
    const submitted = await api('/api/decks', { method: 'POST', ...jsonBody(payload) });
    toast(payload.resume ? 'Generation with resume queued' : 'Generation queued', 'ok');
    followJob(submitted, { kindLabel: 'generate' });
  } catch (error) {
    toast(`Could not queue generation: ${error.message}`);
  }
}

async function resumeDeck(deckId) {
  const payload = collectGenerationPayload({ resume: true });
  const { sources, ...genOptions } = payload;
  try {
    const submitted = await api(`/api/decks/${deckId}/generate`, { method: 'POST', ...jsonBody(genOptions) });
    toast(`Deck generation resumed for ${deckId.slice(0, 8)}`, 'ok');
    followJob(submitted, { kindLabel: 'generate' });
  } catch (error) {
    toast(`Could not resume deck: ${error.message}`);
  }
}

async function resumeDeckJob(job) {
  const deckId = job.deck_id || (job.result && job.result.deck_id);
  if (!deckId) {
    toast('Cannot resume: no deck associated with this task', 'warn');
    return;
  }
  await resumeDeck(deckId);
}

/* ---------------- job following (SSE + polling fallback) ---------------- */
const STAGE_LABELS = {
  parsing: 'Parsing source document',
  'structural validation': 'Validating structure',
  'knowledge extraction': 'Extracting knowledge units',
  'asset understanding': 'Interpreting figures, formulas and tables',
  composition: 'Composing slides',
  build: 'Rendering PPTX',
  'quality checks': 'Quality gate + visual audit',
  publication: 'Publishing revision',
};

function jobRow(job, kindLabel) {
  const row = el('div', 'job');
  const title = el('div', 'jtitle');
  title.append(el('span', 'kind', kindLabel || job.kind), el('span', 'jid', job.id.slice(0, 10)));
  const stage = el('div', 'jstage');
  const right = el('div', 'jlink');
  row.append(title, stage, right);
  const track = el('div', 'progress-track');
  const fill = el('div', 'progress-fill');
  track.append(fill);
  row.append(track);
  return { row, stage, right, fill };
}

function drawJob(card, job) {
  const labels = { queued: 'queued', running: '', completed: 'done', failed: 'failed', cancelled: 'cancelled' };
  card.row.classList.toggle('done', job.status === 'completed');
  card.row.classList.toggle('failed', job.status === 'failed');
  const running = job.status === 'running' || job.status === 'queued';
  if (running) {
    const spinner = el('span', 'spinner');
    const label = el('span', undefined, `${STAGE_LABELS[job.stage] || job.stage || 'waiting for worker'}…`);
    card.stage.replaceChildren(spinner, label);
  } else {
    card.stage.textContent = labels[job.status] || job.status;
  }
  const progress = job.progress || {};
  let fraction = 0;
  if (progress.total) fraction = Math.min(1, (progress.completed || 0) / progress.total);
  else if (job.status === 'completed') fraction = 1;
  card.fill.style.width = `${Math.round(fraction * 100)}%`;

  card.right.replaceChildren();
  if (job.status === 'running' || job.status === 'queued') {
    const cancel = el('button', 'cancel', 'cancel');
    cancel.onclick = () => api(`/api/jobs/${job.id}/cancel`, { method: 'POST' }).catch(e => toast(e.message));
    card.right.append(cancel);
  }
  const isDeckJob = (job.kind === 'generate') || Boolean(job.deck_id);
  if (isDeckJob && ['failed', 'cancelled', 'completed'].includes(job.status)) {
    const resumeBtn = el('button', 'resume-btn', '⚡ resume');
    resumeBtn.title = 'Resume this deck generation task from checkpoints';
    resumeBtn.onclick = () => resumeDeckJob(job);
    card.right.append(resumeBtn);
  }
  if (job.status === 'completed' && job.result && job.result.deck_id) {
    const open = el('a', undefined, 'view deck');
    open.href = '#';
    open.onclick = (event) => { event.preventDefault(); openDeck(job.result.deck_id); };
    card.right.append(open);
  }
  let errorNode = card.row.querySelector('.jerr');
  if (job.error && job.error.message) {
    if (!errorNode) { errorNode = el('div', 'jerr'); card.row.append(errorNode); }
    errorNode.textContent = `${job.error.code || 'ERROR'}: ${job.error.message}`;
  } else if (errorNode) errorNode.remove();
}

function followJob(submitted, opts = {}) {
  const jobId = submitted.job_id || submitted.id;
  if (!jobId || state.jobs.has(jobId)) return;
  // Normalize: API submissions use job_id; job records use id.
  submitted = { ...submitted, id: jobId, job_id: jobId };
  const card = jobRow({ ...submitted, kind: opts.kindLabel || submitted.kind || 'job' });
  state.jobs.set(jobId, { card, terminal: false });
  const container = $('jobs');
  container.querySelector('.empty')?.remove();
  container.prepend(card.row);
  drawJob(card, submitted);

  const finish = (job) => {
    drawJob(card, job);
    if (['completed', 'failed', 'cancelled'].includes(job.status)) {
      const tracked = state.jobs.get(job.id || jobId);
      if (tracked) tracked.terminal = true;
      if (job.es) job.es.close();
      if (job.poll) clearInterval(job.poll);
      if (opts.docId) onParseUpdate(opts.docId, job);
      if (job.status === 'completed' && job.result && job.result.deck_id) refreshDecks().then(() => openDeck(job.result.deck_id));
      if (job.status === 'failed') toast(`Job failed: ${(job.error && job.error.message) || 'unknown error'}`);
    }
  };

  const handle = (job) => {
    const tracked = state.jobs.get(job.id || jobId);
    if (tracked && tracked.terminal) return;
    finish(job);
  };

  // SSE stream for live updates…
  try {
    const es = new EventSource(`/api/jobs/${jobId}/events`);
    es.addEventListener('progress', (event) => { try { handle(JSON.parse(event.data)); } catch { /* ignore */ } });
    es.onerror = () => { /* closed by server on terminal state */ };
    state.jobs.get(jobId).es = es;
  } catch { /* EventSource unavailable */ }
  // …and a polling safety net (also covers SSE failures).
  const poll = setInterval(async () => {
    const tracked = state.jobs.get(jobId);
    if (!tracked || tracked.terminal) { clearInterval(poll); return; }
    try {
      const job = await api(`/api/jobs/${jobId}`);
      handle({ ...job, poll: undefined });
      if (['completed', 'failed', 'cancelled'].includes(job.status)) clearInterval(poll);
    } catch { /* transient */ }
  }, 2000);
  state.jobs.get(submitted.job_id).poll = poll;
}

async function resumeInProgress() {
  try {
    const jobs = await api('/api/jobs?limit=30');
    for (const job of jobs) {
      if (['queued', 'running'].includes(job.status)) {
        followJob(job, { kindLabel: job.kind });
      }
    }
  } catch { /* ignore */ }
}

/* ---------------- decks ---------------- */
async function refreshDecks() {
  try {
    state.decks = await api('/api/decks');
    renderDeckList();
  } catch { /* ignore */ }
}

function renderDeckList() {
  const container = $('decks');
  container.replaceChildren();
  if (!state.decks.length) {
    container.append(el('div', 'empty', 'No decks yet.'));
    return;
  }
  for (const deck of state.decks) {
    const row = el('div', 'deck' + (deck.id === state.selectedDeck ? ' selected' : ''));
    const name = el('div', 'dname', deck.filename || `deck ${deck.id.slice(0, 8)}`);
    const sub = el('div', 'dsub', `${deck.id.slice(0, 12)}… · ${new Date(deck.created_at).toLocaleString()}`);
    const rev = el('span', `rev-tag${deck.active_revision ? '' : ' none'}`,
      deck.active_revision ? `rev ${deck.active_revision.slice(0, 8)}` : 'no revision');
    row.append(name, sub, rev);
    row.onclick = () => openDeck(deck.id);
    container.append(row);
  }
}

async function openDeck(deckId) {
  state.selectedDeck = deckId;
  renderDeckList();
  const detail = $('deck-detail');
  detail.hidden = false;
  detail.replaceChildren(el('div', 'empty', 'loading deck…'));
  let deck;
  try {
    deck = await api(`/api/decks/${deckId}`);
  } catch (error) {
    detail.replaceChildren(el('div', 'jerr', `Could not load deck: ${error.message}`));
    return;
  }
  detail.replaceChildren();
  const active = deck.active_revision;
  const head = el('div', 'dd-head');
  head.append(el('div', 'dd-title', (deck.sources[0] && deck.sources[0].filename) || `Deck ${deckId.slice(0, 8)}`));
  head.append(el('div', 'dd-meta', `${(active && active.previews || []).length} slides · ${active ? active.operation : '—'} · ${active ? new Date(active.created_at).toLocaleString() : ''}`));
  detail.append(head);
  if (!active) {
    const emptyNotice = el('div', 'empty', 'This deck has no published revision yet (job still running or failed).');
    const actions = el('div', 'dd-actions');
    const resumeBtn = el('button', undefined, '⚡ Resume generation');
    resumeBtn.title = 'Resume deck generation with cache checkpoints';
    resumeBtn.onclick = () => resumeDeck(deckId);
    actions.append(resumeBtn);
    detail.append(emptyNotice, actions);
    return;
  }
  const actions = el('div', 'dd-actions');
  const download = el('a', undefined, '⬇ Download .pptx');
  download.href = active.pptx_url;
  const resumeBtn = el('button', undefined, '⚡ Resume generation');
  resumeBtn.title = 'Resume or re-run deck generation reusing cached checkpoints';
  resumeBtn.onclick = () => resumeDeck(deckId);
  actions.append(download, resumeBtn);
  detail.append(actions);

  const checks = el('div', 'checks');
  const label = { PASSED: ['ok', '✓'], EVALUATED_PASS: ['ok', '✓'], FAILED_TO_RUN: ['bad', '✕'], EVALUATED_FAIL: ['bad', '✕'], NOT_EVALUATED: ['', '–'], PARTIAL: ['warn', '!'] };
  for (const [name, status] of Object.entries(active.checks || {})) {
    const [cls, mark] = label[status] || ['', '·'];
    checks.append(el('span', `check-pill ${cls}`, `${mark} ${name}: ${status}`));
  }
  checks.append(el('span', `check-pill ${active.readiness === 'PASSED' ? 'ok' : 'warn'}`, `readiness: ${active.readiness}`));
  detail.append(checks);

  if (active.previews && active.previews.length) {
    const grid = el('div', 'preview-grid');
    for (const preview of active.previews) {
      const card = el('div', 'slide-card');
      const img = el('img');
      img.loading = 'lazy';
      img.src = preview.url;
      img.alt = `Slide ${preview.slide} preview`;
      const cap = el('div', 'cap');
      cap.append(el('span', undefined, `slide ${preview.slide}`), el('span', undefined, 'rendered'));
      card.append(img, cap);
      grid.append(card);
    }
    detail.append(grid);
  } else {
    detail.append(el('div', 'empty', 'No rendered previews available for this revision (rendering may have been unavailable on this machine).'));
  }
}

/* ---------------- wiring ---------------- */
function wireUpload() {
  const zone = $('dropzone');
  const input = $('file-input');
  zone.onclick = () => input.click();
  zone.onkeydown = (event) => { if (event.key === 'Enter' || event.key === ' ') input.click(); };
  input.onchange = () => { uploadFiles([...input.files]); input.value = ''; };
  ['dragenter', 'dragover'].forEach(name => zone.addEventListener(name, (event) => {
    event.preventDefault(); zone.classList.add('dragging');
  }));
  ['dragleave', 'drop'].forEach(name => zone.addEventListener(name, (event) => {
    event.preventDefault(); zone.classList.remove('dragging');
  }));
  zone.addEventListener('drop', (event) => {
    const files = [...event.dataTransfer.files];
    if (files.length) uploadFiles(files);
  });
}

function wireSettings() {
  $('generate').onclick = () => generate();
  if ($('resume-generate')) {
    $('resume-generate').onclick = () => {
      if ($('resume_cache')) $('resume_cache').checked = true;
      generate({ resume: true });
    };
  }
  $('refresh-decks').onclick = () => { refreshDecks(); toast('Deck list refreshed', 'info'); };
  $('lens').addEventListener('change', populateThemes);
}

async function init() {
  wireUpload();
  wireSettings();
  try {
    await Promise.all([loadConfig(), loadFormats()]);
  } catch (error) {
    toast(`Could not load server configuration: ${error.message}`);
  }
  pollWorker();
  setInterval(pollWorker, 5000);
  refreshDecks();
  resumeInProgress();
  updateGenerateButton();
}

init();
