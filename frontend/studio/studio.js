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
  docs: new Map(),      // document_id -> {view, status, parseJobId, findings[], removed}
  jobs: new Map(),      // job_id -> {card, es, poll, terminal, status, kind}
  decks: [],
  selectedDeck: null,
  uploading: false,
  decksLoading: false,
  decksError: false,
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
    pill.className = `status-pill state-${status.state}`;
    const labels = { alive: 'worker online', busy: 'worker busy', stale: 'worker stale — restart it', offline: 'worker offline' };
    $('worker-state').textContent = labels[status.state] || status.state;
    pill.title = status.age_seconds !== null ? `heartbeat ${status.age_seconds}s ago (pid ${status.pid ?? '?'})` : 'no heartbeat yet';
  } catch { /* transient */ }
}

async function loadConfig() {
  try {
    const previous = state.config && state.config.model;
    state.config = await api('/api/config');
    const c = state.config;
    const chip = $('model-chip');
    const quota = (c.models || []).find(model => model.current);
    let text = `${c.provider} · ${c.model}`;
    if (quota) text += ` · ${quota.rpm}/min · ${quota.tpm === null ? 'TPM uncapped' : `${formatTokens(quota.tpm)}/min`}`;
    if (quota && quota.rpd) text += ` · ${quota.rpd}/day`;
    if (c.context_tokens) text += ` · ctx ${formatTokens(c.context_tokens)}`;
    chip.textContent = text;
    chip.title = quota && quota.declared
      ? `declared quotas are enforced before each call · strict coverage: ${c.strict_section_coverage ? 'on' : 'off'} · concurrency ${c.max_concurrency}`
      : `no declared quota for ${c.model}: only the configured ${c.max_calls_per_minute} calls/min cap applies`;
    chip.classList.toggle('nokey', !c.api_key_present);
    if (!c.api_key_present) chip.title += ' · API key missing';
    populateThemes();
    populateModels();
    if (previous && previous !== c.model) toast(`Provider default is now ${c.model}`, 'ok');
  } catch (error) { $('model-chip').textContent = 'config unavailable'; }
}

function formatTokens(value) {
  return value >= 1000 ? `${Math.round((value / 1000) * 10) / 10}K` : `${value}`;
}

function modelQuota(model) {
  return ((state.config || {}).models || []).find(entry => entry.model === model) || null;
}

function populateModels() {
  const select = $('model');
  if (!select || !state.config || !state.config.models) return;
  const signature = JSON.stringify(state.config.models);
  // A re-poll must not rebuild an untouched control: rebuilding closes an open dropdown.
  if (signature === state.modelSignature) { updateModelNote(); return; }
  state.modelSignature = signature;
  const current = select.value || '';
  const options = [`<option value="">Provider default — ${state.config.model}</option>`];
  for (const model of state.config.models) {
    const tier = model.current ? ' — provider default' : '';
    const limits = `${model.rpm}/min · ${model.tpm === null ? 'TPM uncapped' : `${formatTokens(model.tpm)}/min`}` +
      `${model.rpd ? ` · ${model.rpd}/day` : ''}`;
    options.push(`<option value="${model.model}">${model.label}${tier} — ${limits}</option>`);
  }
  select.innerHTML = options.join('');
  select.value = [...select.options].some(o => o.value === current) ? current : '';
  updateModelNote();
}

function updateModelNote() {
  const note = $('model-note');
  if (!note || !state.config) return;
  const chosen = $('model').value;
  const used = chosen || state.config.model;
  const quota = modelQuota(used);
  if (!quota) { note.textContent = 'limits are enforced per model before the provider is called'; return; }
  const limits = `${used} · ${quota.rpm} calls per minute, ${quota.tpm === null ? 'no' : formatTokens(quota.tpm)} tokens per minute` +
    (quota.rpd ? `, ${quota.rpd} calls per day` : '');
  // A chosen model pins every tier, so the server's separate fast tier only applies
  // to the provider default.
  const tiers = chosen ? 'every stage uses this model'
    : state.config.fast_model && state.config.fast_model !== used ? `fast tier ${state.config.fast_model}` : '';
  note.textContent = [limits, tiers, quota.declared ? '' : 'quota not declared, process cap only'].filter(Boolean).join(' · ');
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
    if (ok.length) $('dz-formats').textContent = ok.join(', ');
  } catch { $('formats-hint').textContent = 'format check failed'; }
}

/* ---------------- stage rail ---------------- */
/* Communicates real client state only — no fabricated progress. */
function updateStages() {
  const docs = [...state.docs.values()];
  const parsed = docs.filter(d => d.status === 'parsed').length;
  const inFlight = docs.filter(d => d.status === 'uploading' || d.status === 'parsing').length;
  const failedDocs = docs.filter(d => d.status === 'failed').length;
  const jobs = [...state.jobs.values()];
  const genJobs = jobs.filter(j => j.kind === 'generate');
  const activeJobs = jobs.filter(j => !j.terminal).length;
  const doneGen = genJobs.filter(j => j.terminal && j.status === 'completed').length;
  const failedJobs = jobs.filter(j => j.terminal && j.status === 'failed').length;

  const setStage = (id, { current = false, done = false, num, note }) => {
    const li = $(id);
    if (!li) return;
    li.classList.toggle('is-current', current);
    li.classList.toggle('is-done', done);
    if (current) li.setAttribute('aria-current', 'step');
    else li.removeAttribute('aria-current');
    const numEl = li.querySelector('.stage-num');
    if (numEl) numEl.textContent = done ? '\u2713' : num;
    const noteEl = li.querySelector('.stage-note');
    if (noteEl && note !== undefined) noteEl.textContent = note;
  };

  let sourceNote;
  if (parsed) sourceNote = inFlight ? `${parsed} parsed · ${inFlight} in flight` : `${parsed} parsed source${parsed > 1 ? 's' : ''}`;
  else if (inFlight) sourceNote = `${inFlight} file${inFlight > 1 ? 's' : ''} uploading / parsing…`;
  else if (failedDocs) sourceNote = 'upload failed — check the row for details';
  else sourceNote = 'select and parse a document';
  setStage('stage-source', { current: parsed === 0, done: parsed > 0, num: '01', note: sourceNote });

  const configureDone = genJobs.length > 0;
  let configureNote;
  if (configureDone) configureNote = doneGen ? 'settings submitted — deck generated' : 'settings submitted';
  else if (parsed) configureNote = 'ready — generate when configured';
  else configureNote = 'narrative, extraction, visuals, limits';
  setStage('stage-configure', { current: parsed > 0 && !configureDone, done: configureDone, num: '02', note: configureNote });

  let reviewNote;
  const parts = [];
  if (activeJobs) parts.push(`${activeJobs} active`);
  if (failedJobs) parts.push(`${failedJobs} failed`);
  if (!parts.length && doneGen) parts.push(`${doneGen} completed`);
  if (!parts.length && state.decks.length) parts.push(`${state.decks.length} deck${state.decks.length > 1 ? 's' : ''}`);
  reviewNote = parts.length ? parts.join(' · ') : 'jobs, decks and exports';
  setStage('stage-review', { current: jobs.length > 0, done: doneGen > 0, num: '03', note: reviewNote });
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

const DOC_LABELS = { uploading: 'uploading', parsing: 'parsing', parsed: 'parsed', failed: 'failed' };

function renderDoc(entry) {
  const row = entry.row;
  row.replaceChildren();
  row.className = `doc status-${entry.status}`;

  const ext = el('span', 'doc-ext', extLabel(entry.view.filename));
  ext.title = 'file type';

  const info = el('div', 'doc-info');
  info.append(el('span', 'doc-name', entry.view.filename));
  const metaBits = [];
  if (typeof entry.view.size_bytes === 'number') metaBits.push(fmtBytes(entry.view.size_bytes));
  const detected = entry.view.upload && entry.view.upload.detected_type;
  if (detected) metaBits.push(`type ${detected}`);
  info.append(el('span', 'doc-meta', metaBits.join(' · ')));

  const status = el('span', 'doc-status');
  if (entry.status === 'uploading' || entry.status === 'parsing') {
    const spinner = el('span', 'spinner');
    spinner.setAttribute('aria-hidden', 'true');
    status.append(spinner, el('span', 'status-text', DOC_LABELS[entry.status]));
  } else {
    const mark = el('span', 'status-mark', entry.status === 'parsed' ? '\u2713' : '\u2715');
    status.append(mark, el('span', 'status-text', DOC_LABELS[entry.status]));
  }

  const remove = el('button', 'doc-remove', '\u00d7');
  remove.type = 'button';
  remove.setAttribute('aria-label', `Remove ${entry.view.filename} from the source set`);
  remove.title = 'Remove from this source set (the upload itself is kept server-side)';
  remove.onclick = () => {
    entry.removed = true;
    if (entry.view.id && state.docs.has(entry.view.id)) state.docs.delete(entry.view.id);
    row.remove();
    updateGenerateButton();
  };

  row.append(ext, info, status, remove);
  if (entry.findings && entry.findings.length) {
    const note = el('div', 'doc-findings');
    note.textContent = entry.findings.join(' · ');
    row.append(note);
  }
  updateGenerateButton();
}

async function uploadFiles(files) {
  state.uploading = true;
  updateGenerateButton();
  try {
    for (const file of files) {
      await uploadOne(file);
    }
  } finally {
    state.uploading = false;
    updateGenerateButton();
  }
}

async function uploadOne(file) {
  // Optimistic row: shows the upload state before the first response arrives.
  const entry = {
    view: { filename: file.name, size_bytes: file.size, upload: null, id: null },
    status: 'uploading', parseJobId: null, findings: [], removed: false,
    row: el('li', 'doc'),
  };
  $('doc-list').prepend(entry.row);
  renderDoc(entry);

  const form = new FormData();
  form.append('file', file);
  form.append('selected_type', 'auto');
  let view;
  try {
    view = await api('/api/documents', { method: 'POST', body: form });
  } catch (error) {
    if (entry.removed) return;
    entry.status = 'failed';
    entry.findings.push(`upload failed: ${error.message}`);
    renderDoc(entry);
    toast(`Upload failed: ${error.message}`, 'error');
    updateStages();
    return;
  }
  if (entry.removed) return; // removed while the request was in flight
  entry.view = view;
  entry.status = 'parsing';
  state.docs.set(view.id, entry);
  renderDoc(entry);
  updateStages();
  try {
    const submitted = await api(`/api/documents/${view.id}/parse`, { method: 'POST', ...jsonBody({}) });
    entry.parseJobId = submitted.job_id;
    followJob(submitted, { kindLabel: 'parse', docId: view.id });
  } catch (error) {
    entry.status = 'failed';
    entry.findings.push(error.message);
    renderDoc(entry);
    toast(`Parse submission failed: ${error.message}`);
    updateStages();
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
  updateStages();
}

function parsedDocs() {
  return [...state.docs.values()].filter(d => d.status === 'parsed');
}

function updateGenerateButton() {
  const count = parsedDocs().length;
  const ready = count > 0;
  $('generate').disabled = !ready || state.uploading;
  if ($('resume-generate')) $('resume-generate').disabled = !ready || state.uploading;
  $('generate-sub').textContent = state.uploading
    ? 'waiting for uploads to finish'
    : (ready ? `${count} parsed source${count > 1 ? 's' : ''} ready` : 'upload and parse a source first');
  if ($('resume-sub')) {
    $('resume-sub').textContent = ready ? 'reuse cache / checkpoints' : 'upload a source first';
  }
  updateStages();
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
    model: ($('model') && $('model').value) || null,
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
  updateStages();
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
  evaluation: 'Running evaluation metrics',
};

const JOB_LABELS = { queued: 'queued', running: 'running', completed: 'completed', failed: 'failed', cancelled: 'cancelled' };
const JOB_MARKS = { queued: '\u25cb', running: '\u25d0', completed: '\u2713', failed: '\u2715', cancelled: '\u2013' };

function jobRow(job, kindLabel) {
  const row = el('article', 'job');
  const head = el('div', 'job-head');
  const kind = el('span', 'job-kind', kindLabel || job.kind || 'job');
  const id = el('span', 'job-id', (job.id || '').slice(0, 10));
  const model = el('span', 'job-model', '');
  const statusWrap = el('span', 'job-status');
  const actions = el('span', 'job-actions');
  head.append(kind, id, model, statusWrap, actions);
  const stage = el('div', 'job-stage');
  const progress = el('div', 'job-progress');
  progress.hidden = true;
  row.append(head, stage, progress);
  return { row, head, kind, id, model, statusWrap, actions, stage, progress };
}

function drawJob(card, job) {
  card.row.dataset.status = job.status;

  /* the model this job runs on, with the quotas the worker enforces for it */
  const quota = ((state.config || {}).models || []).find(model => model.model === job.model);
  card.model.textContent = job.model || '';
  card.model.title = quota
    ? `${quota.label} — ${quota.rpm} calls/min · ${quota.tpm ?? 'unbounded'} tokens/min` +
      `${quota.rpd ? ` · ${quota.rpd} calls/day` : ''}${quota.declared ? '' : ' · quota not declared'}`
    : 'provider model';

  /* status: mark + text, never color alone */
  card.statusWrap.replaceChildren();
  const mark = el('span', 'status-mark', JOB_MARKS[job.status] ?? '\u00b7');
  if (job.status === 'running') {
    mark.textContent = '';
    mark.className = 'status-mark spinner';
    mark.setAttribute('aria-hidden', 'true');
  }
  card.statusWrap.append(mark, el('span', 'status-text', JOB_LABELS[job.status] || job.status));

  /* stage line */
  if (job.status === 'running') {
    const spinner = el('span', 'spinner');
    spinner.setAttribute('aria-hidden', 'true');
    card.stage.replaceChildren(spinner, el('span', undefined, `${STAGE_LABELS[job.stage] || job.stage || 'running'}…`));
  } else if (job.status === 'queued') {
    card.stage.textContent = job.cancel_requested
      ? 'cancellation requested — waiting for worker'
      : 'waiting for an available worker';
  } else {
    const doneWord = job.status === 'completed' ? 'finished' : JOB_LABELS[job.status];
    card.stage.textContent = job.stage ? `${STAGE_LABELS[job.stage] || job.stage} — ${doneWord}` : doneWord;
  }

  /* progress: determinate bar only when the backend reports a trustworthy total */
  const progress = job.progress || {};
  const total = typeof progress.total === 'number' && progress.total > 0 ? progress.total : 0;
  if (total && (job.status === 'running' || job.status === 'completed')) {
    const completed = typeof progress.completed === 'number'
      ? Math.max(0, Math.min(progress.completed, total)) : 0;
    card.progress.hidden = false;
    card.progress.replaceChildren();
    const track = el('div', 'progress-track');
    const fill = el('div', 'progress-fill');
    fill.style.width = job.status === 'completed' ? '100%' : `${Math.round((completed / total) * 100)}%`;
    track.append(fill);
    card.progress.append(track, el('span', 'progress-num', job.status === 'completed' ? `${total}/${total}` : `${completed}/${total}`));
  } else {
    card.progress.hidden = true;
  }

  /* actions */
  card.actions.replaceChildren();
  if ((job.status === 'running' || job.status === 'queued') && !job.cancel_requested) {
    const cancel = el('button', 'btn-mini danger', 'cancel');
    cancel.type = 'button';
    cancel.onclick = async () => {
      cancel.disabled = true;
      cancel.textContent = 'cancelling…';
      try { await api(`/api/jobs/${job.id}/cancel`, { method: 'POST' }); }
      catch (e) { cancel.disabled = false; cancel.textContent = 'cancel'; toast(e.message); }
    };
    card.actions.append(cancel);
  } else if ((job.status === 'running' || job.status === 'queued') && job.cancel_requested) {
    card.actions.append(el('span', 'job-cancel-note', 'cancelling'));
  }
  const isDeckJob = (job.kind === 'generate') || Boolean(job.deck_id);
  if (isDeckJob && ['failed', 'cancelled', 'completed'].includes(job.status)) {
    const resumeBtn = el('button', 'btn-mini accent', 'resume');
    resumeBtn.type = 'button';
    resumeBtn.title = 'Resume this deck generation task from checkpoints';
    resumeBtn.onclick = () => resumeDeckJob(job);
    card.actions.append(resumeBtn);
  }
  if (job.status === 'completed' && job.result && job.result.deck_id) {
    const open = el('a', 'btn-mini accent', 'view deck');
    open.href = '#';
    open.onclick = (event) => { event.preventDefault(); openDeck(job.result.deck_id); };
    card.actions.append(open);
  }

  /* expandable error details */
  let errBox = card.row.querySelector('.job-error');
  if (job.error && job.error.message) {
    if (!errBox) { errBox = el('details', 'job-error'); card.row.append(errBox); }
    const summary = el('summary');
    summary.append(
      el('span', 'err-mark', '\u2715'),
      el('span', 'err-code', job.error.code || 'ERROR'),
      el('span', 'err-short', job.error.message),
    );
    summary.title = job.error.message;
    const full = el('pre', 'err-full', `${job.error.code || 'ERROR'}: ${job.error.message}${job.error.stage ? `\nstage: ${job.error.stage}` : ''}`);
    errBox.replaceChildren(summary, full);
  } else if (errBox) errBox.remove();
}

function followJob(submitted, opts = {}) {
  const jobId = submitted.job_id || submitted.id;
  if (!jobId || state.jobs.has(jobId)) return;
  // Normalize: API submissions use job_id; job records use id.
  submitted = { ...submitted, id: jobId, job_id: jobId };
  const kind = opts.kindLabel || submitted.kind || 'job';
  const card = jobRow({ ...submitted, kind });
  state.jobs.set(jobId, { card, terminal: false, status: submitted.status || 'queued', kind });
  const container = $('jobs');
  container.querySelector('.empty-state')?.remove();
  container.prepend(card.row);
  drawJob(card, submitted);
  updateStages();

  const finish = (job) => {
    drawJob(card, job);
    if (['completed', 'failed', 'cancelled'].includes(job.status)) {
      const tracked = state.jobs.get(job.id || jobId);
      if (tracked) { tracked.terminal = true; tracked.status = job.status; }
      if (job.es) job.es.close();
      if (job.poll) clearInterval(job.poll);
      if (opts.docId) onParseUpdate(opts.docId, job);
      if (job.status === 'completed' && job.result && job.result.deck_id) refreshDecks().then(() => openDeck(job.result.deck_id));
      if (job.status === 'failed') toast(`Job failed: ${(job.error && job.error.message) || 'unknown error'}`);
      updateStages();
    }
  };

  const handle = (job) => {
    const tracked = state.jobs.get(job.id || jobId);
    if (tracked && tracked.terminal) return;
    if (tracked) tracked.status = job.status;
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
  if (state.decksLoading) return;
  state.decksLoading = true;
  state.decksError = false;
  renderDeckList();
  try {
    state.decks = await api('/api/decks');
  } catch (error) {
    state.decksError = true;
    state.decks = [];
  } finally {
    state.decksLoading = false;
    renderDeckList();
    updateStages();
  }
}

function renderDeckList() {
  const container = $('decks');
  container.replaceChildren();

  if (state.decksLoading) {
    container.setAttribute('aria-busy', 'true');
    for (let i = 0; i < 3; i += 1) container.append(el('div', 'skeleton-row'));
    return;
  }
  container.removeAttribute('aria-busy');

  if (state.decksError) {
    const box = el('div', 'empty-state is-error');
    box.append(
      el('p', 'empty-title', 'Could not load decks'),
      el('p', 'empty-sub', 'Check the API connection, then press Refresh.'),
    );
    container.append(box);
    return;
  }

  if (!state.decks.length) {
    const box = el('div', 'empty-state');
    box.append(
      el('p', 'empty-title', 'No decks yet'),
      el('p', 'empty-sub', 'Generated decks are published here with revisions, checks and downloads.'),
    );
    container.append(box);
    return;
  }

  for (const deck of state.decks) {
    const row = el('button', `deck-row${deck.id === state.selectedDeck ? ' selected' : ''}`);
    row.type = 'button';
    const name = el('span', 'deck-name', deck.filename || `deck ${deck.id.slice(0, 8)}`);
    const when = new Date(deck.created_at);
    const time = Number.isNaN(when.getTime()) ? '' : ` · ${when.toLocaleString()}`;
    const meta = el('span', 'deck-meta',
      `${deck.active_revision ? `rev ${deck.active_revision.slice(0, 8)}` : 'no revision yet'}${time}`);
    const stateLabel = el('span', `deck-state${deck.active_revision ? '' : ' none'}`,
      deck.active_revision ? 'published' : 'pending');
    row.append(name, meta, stateLabel);
    row.setAttribute('aria-label', `Open deck ${deck.filename || deck.id}`);
    row.onclick = () => openDeck(deck.id);
    container.append(row);
  }
}

async function openDeck(deckId) {
  state.selectedDeck = deckId;
  saveUiState();
  renderDeckList();
  const detail = $('deck-detail');
  detail.hidden = false;
  detail.replaceChildren();
  const loading = el('div', 'detail-loading');
  loading.append(el('span', 'spinner'), el('span', undefined, 'Loading deck…'));
  detail.append(loading);
  let deck;
  try {
    deck = await api(`/api/decks/${deckId}`);
  } catch (error) {
    detail.replaceChildren(el('p', 'detail-error', `Could not load deck: ${error.message}`));
    return;
  }
  detail.replaceChildren();
  const active = deck.active_revision;

  const head = el('div', 'detail-head');
  head.append(
    el('h3', 'detail-title', (deck.sources[0] && deck.sources[0].filename) || `Deck ${deckId.slice(0, 8)}`),
    el('div', 'detail-meta', `deck ${deckId.slice(0, 12)} · created ${new Date(deck.created_at).toLocaleString()}`),
  );
  detail.append(head);

  if (!active) {
    detail.append(el('p', 'notice', 'This deck has no published revision yet — its job may still be running or failed.'));
    const actions = el('div', 'detail-actions');
    const resumeBtn = el('button', undefined, 'Resume generation');
    resumeBtn.type = 'button';
    resumeBtn.title = 'Resume deck generation with cache checkpoints';
    resumeBtn.onclick = () => resumeDeck(deckId);
    actions.append(resumeBtn);
    detail.append(actions);
    return;
  }

  const actions = el('div', 'detail-actions');
  const download = el('a', undefined, 'Download .pptx');
  download.href = active.pptx_url;
  download.setAttribute('download', '');
  const resumeBtn = el('button', undefined, 'Resume generation');
  resumeBtn.type = 'button';
  resumeBtn.title = 'Resume or re-run deck generation reusing cached checkpoints';
  resumeBtn.onclick = () => resumeDeck(deckId);
  actions.append(download, resumeBtn);
  detail.append(actions);

  const checks = el('div', 'checks');
  const checkMarks = {
    PASSED: ['ok', '\u2713'], EVALUATED_PASS: ['ok', '\u2713'],
    FAILED_TO_RUN: ['bad', '\u2715'], EVALUATED_FAIL: ['bad', '\u2715'],
    PARTIAL: ['warn', '!'], NOT_EVALUATED: ['none', '\u2013'],
  };
  for (const [name, status] of Object.entries(active.checks || {})) {
    const [cls, glyph] = checkMarks[status] || ['none', '\u00b7'];
    const row = el('div', 'check-row');
    row.append(
      el('span', `mark ${cls}`, glyph),
      el('span', 'check-name', name),
      el('span', 'check-status', status),
    );
    checks.append(row);
  }
  const readinessRow = el('div', 'check-row');
  const readinessCls = active.readiness === 'PASSED' ? 'ok' : 'warn';
  readinessRow.append(
    el('span', `mark ${readinessCls}`, readinessCls === 'ok' ? '\u2713' : '!'),
    el('span', 'check-name', 'readiness'),
    el('span', 'check-status', active.readiness),
  );
  checks.append(readinessRow);
  detail.append(checks);

  if (active.missing_checks && active.missing_checks.length) {
    detail.append(el('p', 'missing-checks', `Missing checks: ${active.missing_checks.join(', ')}`));
  }

  /* F19 evaluation metrics panel (auto-run after generation; re-runnable) */
  const evalPanel = el('section', 'eval-panel');
  detail.append(evalPanel);
  renderEvaluationPanel(evalPanel, deckId, active.revision_id);

  if (active.previews && active.previews.length) {
    const grid = el('div', 'preview-grid');
    for (const preview of active.previews) {
      const slideCard = el('div', 'slide-card');
      const img = el('img');
      img.loading = 'lazy';
      img.src = preview.url;
      img.alt = `Slide ${preview.slide} preview`;
      const cap = el('div', 'cap');
      cap.append(el('span', undefined, `slide ${preview.slide}`), el('span', undefined, 'rendered'));
      slideCard.append(img, cap);
      grid.append(slideCard);
    }
    detail.append(grid);
  } else {
    detail.append(el('p', 'notice', 'No rendered previews available for this revision (rendering may have been unavailable on this machine).'));
  }
}

/* ---------------- evaluation metrics panel (F19) ---------------- */
const METRIC_LABELS = {
  semantic: 'Semantic', coverage: 'Coverage', faithfulness: 'Faithfulness',
  functional: 'Functional', structure: 'Structure', visual: 'Visual',
};

function scoreBand(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 'none';
  const numeric = Number(value);
  if (numeric >= 0.8) return 'ok';
  if (numeric >= 0.6) return 'warn';
  return 'bad';
}

function scoreRingNode(value, caption) {
  const band = scoreBand(value);
  const pct = value === null || value === undefined ? 0 : Math.max(0, Math.min(1, Number(value)));
  const size = 88, radius = 36, circumference = 2 * Math.PI * radius;
  const ring = el('div', `score-ring ${band}`);
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${size} ${size}`);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', caption);
  const track = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
  track.setAttribute('cx', size / 2); track.setAttribute('cy', size / 2); track.setAttribute('r', radius);
  track.setAttribute('class', 'ring-track');
  const fill = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
  fill.setAttribute('cx', size / 2); fill.setAttribute('cy', size / 2); fill.setAttribute('r', radius);
  fill.setAttribute('class', 'ring-fill');
  fill.setAttribute('stroke-dasharray', `${circumference}`);
  fill.setAttribute('stroke-dashoffset', `${circumference * (1 - pct)}`);
  fill.setAttribute('transform', `rotate(-90 ${size / 2} ${size / 2})`);
  svg.append(track, fill);
  const label = el('span', 'ring-value', value === null || value === undefined ? '—' : `${Math.round(pct * 100)}`);
  const sub = el('span', 'ring-sub', 'overall');
  ring.append(svg, label, sub);
  return ring;
}

function metricCard(metric) {
  const band = scoreBand(metric.score);
  const card = el('div', `metric-card ${band}`);
  const head = el('div', 'metric-head');
  head.append(el('span', 'metric-name', METRIC_LABELS[metric.name] || metric.name));
  if (metric.status && !['COMPLETED', 'EVALUATED_PASS', 'NOT_APPLICABLE'].includes(metric.status)) {
    head.append(el('span', 'metric-status', metric.status));
  }
  head.append(el('span', `metric-value ${band}`,
    metric.score === null || metric.score === undefined ? '—' : Number(metric.score).toFixed(2)));
  card.append(head);
  const track = el('div', 'metric-track');
  const fill = el('div', `metric-fill ${band}`);
  const pct = metric.score === null || metric.score === undefined ? 0
    : Math.max(2, Math.min(100, Math.round(Number(metric.score) * 100)));
  fill.style.width = `${pct}%`;
  track.append(fill);
  card.append(track);
  return card;
}

function countChips(title, pairs) {
  const group = el('span', 'count-group');
  group.append(el('span', 'count-title', title));
  for (const [label, count, cls] of pairs) {
    if (!count) continue;
    group.append(el('span', `count-chip ${cls}`, `${count} ${label}`));
  }
  return group;
}

function renderEvaluationSummary(summary) {
  const nodes = [];
  const shown = summary.overall !== null && summary.overall !== undefined
    ? summary.overall : summary.available_metrics_score;

  const hero = el('div', 'eval-hero');
  hero.append(scoreRingNode(shown, 'overall evaluation score'));
  const heroMeta = el('div', 'eval-hero-meta');
  const readinessCls = summary.readiness === 'BLOCKED' ? 'bad'
    : summary.readiness === 'DRAFT_INCOMPLETE' ? 'warn' : 'ok';
  heroMeta.append(el('span', `eval-readiness ${readinessCls}`, summary.readiness || 'UNKNOWN'));
  const stamp = (summary.run && summary.run.timestamp)
    ? new Date(summary.run.timestamp).toLocaleString() : '';
  if (stamp) heroMeta.append(el('span', 'eval-stamp', stamp));
  if ((summary.run && summary.run.ai_judging) === false) {
    heroMeta.append(el('span', 'eval-flag', 'no AI judging'));
  }
  if ((summary.run && summary.run.embedding_backend) === 'tfidf_fallback') {
    heroMeta.append(el('span', 'eval-flag', 'tf-idf fallback'));
  }
  if (summary.overall === null || summary.overall === undefined) {
    heroMeta.append(el('span', 'eval-note',
      'overall withheld — required checks incomplete; ring shows the available-metrics score'));
  }
  hero.append(heroMeta);
  nodes.push(hero);

  const grid = el('div', 'eval-metrics');
  for (const metric of summary.metrics || []) grid.append(metricCard(metric));
  nodes.push(grid);

  const counts = el('div', 'eval-counts');
  const coverage = (summary.coverage && summary.coverage.counts) || null;
  if (coverage) {
    counts.append(countChips('coverage', [
      ['covered', coverage.COVERED, 'ok'],
      ['partial', coverage.PARTIALLY_COVERED, 'warn'],
      ['missing', coverage.MISSING, 'bad'],
    ]));
  }
  const faith = summary.faithfulness || null;
  if (faith && faith.counts) {
    counts.append(countChips('claims', [
      ['supported', faith.counts.SUPPORTED, 'ok'],
      ['partial', faith.counts.PARTIALLY_SUPPORTED, 'warn'],
      ['unsupported', faith.counts.UNSUPPORTED, 'bad'],
      ['contradicted', faith.counts.CONTRADICTED, 'bad'],
    ]));
  }
  if (summary.warning_count) {
    counts.append(countChips('warnings', [['visual warnings', summary.warning_count, 'warn']]));
  }
  if (counts.childNodes.length) nodes.push(counts);

  if ((summary.skipped_metrics || []).length) {
    nodes.push(el('p', 'eval-note',
      `Skipped metrics: ${summary.skipped_metrics.map(item => item.metric).join(', ')}`));
  }
  if (summary.report_url) {
    const reportLink = el('a', 'eval-report-link', 'download full report');
    reportLink.href = summary.report_url;
    reportLink.setAttribute('download', '');
    nodes.push(reportLink);
  }
  return nodes;
}

async function renderEvaluationPanel(panel, deckId, revisionId) {
  panel.replaceChildren();
  const head = el('div', 'eval-head');
  head.append(el('h4', 'eval-title', 'Evaluation metrics'));
  const actions = el('span', 'eval-actions');
  head.append(actions);
  panel.append(head);
  const body = el('div', 'eval-body');
  const loading = el('div', 'eval-loading');
  loading.append(el('span', 'spinner'), el('span', undefined, 'Loading evaluation…'));
  body.append(loading);
  panel.append(body);

  let summary = null;
  try {
    summary = await api(`/api/decks/${deckId}/revisions/${revisionId}/evaluation`);
  } catch (error) {
    if (error.status !== 404) {
      body.replaceChildren(el('p', 'eval-error', `Could not load evaluation: ${error.message}`));
      return;
    }
    /* 404 = not evaluated yet: fall through to the empty state */
  }

  const runBtn = el('button', 'eval-run');
  runBtn.type = 'button';
  runBtn.textContent = summary ? 'Re-run evaluation' : 'Run evaluation';
  runBtn.title = 'Queue the full metric evaluation (semantic, coverage, faithfulness, functional, structure, visual)';
  runBtn.onclick = () => { runBtn.disabled = true; runEvaluation(deckId, revisionId); };
  actions.append(runBtn);

  if (!summary) {
    const empty = el('div', 'eval-empty');
    empty.append(
      el('span', 'eval-empty-mark', '\u25b6'),
      el('span', undefined, 'Not evaluated yet — run the full metric set for this revision.'),
    );
    body.replaceChildren(empty);
    return;
  }
  body.replaceChildren(...renderEvaluationSummary(summary));
}

async function runEvaluation(deckId, revisionId) {
  try {
    const submitted = await api(`/api/decks/${deckId}/revisions/${revisionId}/evaluate`, { method: 'POST' });
    toast('Evaluation queued', 'ok');
    followJob(submitted, { kindLabel: 'evaluate' });
  } catch (error) {
    toast(`Could not queue evaluation: ${error.message}`);
    const panel = document.querySelector('.eval-panel');
    if (panel) renderEvaluationPanel(panel, deckId, revisionId);
  }
}

/* ---------------- UI state persistence (survives reload) ---------------- */
const STORAGE_KEY = 'pptai.studio.v1';
const PERSISTED_FIELDS = ['lens', 'instruction', 'extraction_mode', 'asset_understanding',
  'model', 'theme', 'polish', 'renderer', 'min_slides', 'max_slides',
  'max_repairs_per_slide', 'max_concurrency'];
const PERSISTED_CHECKS = ['dynamic_layout', 'deep_verification', 'resume_cache'];

function saveUiState() {
  try {
    const form = {};
    for (const id of PERSISTED_FIELDS) {
      const node = $(id);
      if (node) form[id] = node.value;
    }
    for (const id of PERSISTED_CHECKS) {
      const node = $(id);
      if (node) form[id] = node.checked;
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ form, lastDeck: state.selectedDeck }));
  } catch { /* storage unavailable (private mode / quota) — persistence is best-effort */ }
}

function restoreUiState() {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null'); } catch { saved = null; }
  if (!saved || !saved.form) return saved || null;
  // Static-option fields restore immediately; theme/model wait for loadConfig().
  for (const id of PERSISTED_FIELDS) {
    if (id === 'theme' || id === 'model') continue;
    const node = $(id);
    if (node && saved.form[id] !== undefined && saved.form[id] !== null) node.value = saved.form[id];
  }
  for (const id of PERSISTED_CHECKS) {
    const node = $(id);
    if (node && typeof saved.form[id] === 'boolean') node.checked = saved.form[id];
  }
  return saved;
}

function restoreDynamicChoices(saved) {
  if (!saved || !saved.form) return;
  for (const id of ['theme', 'model']) {
    const node = $(id);
    const value = saved.form[id];
    if (node && value) {
      node.value = value;
      if (node.value !== value) node.value = id === 'theme' ? 'auto' : '';
    }
  }
  if (typeof updateModelNote === 'function') updateModelNote();
}

function wirePersistence() {
  for (const id of [...PERSISTED_FIELDS, ...PERSISTED_CHECKS]) {
    const node = $(id);
    if (!node) continue;
    node.addEventListener('change', saveUiState);
    if (node.tagName === 'TEXTAREA') node.addEventListener('input', saveUiState);
  }
}

/* ---------------- wiring ---------------- */
function wireUpload() {
  const zone = $('dropzone');
  const input = $('file-input');
  zone.onclick = () => input.click();
  zone.onkeydown = (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); input.click(); } };
  input.onchange = () => { uploadFiles([...input.files]); input.value = ''; };
  ['dragenter', 'dragover'].forEach(name => zone.addEventListener(name, (event) => {
    event.preventDefault(); event.stopPropagation(); zone.classList.add('dragging');
  }));
  ['dragleave', 'drop'].forEach(name => zone.addEventListener(name, (event) => {
    event.preventDefault(); event.stopPropagation(); zone.classList.remove('dragging');
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
  if ($('model')) $('model').addEventListener('change', updateModelNote);
}

async function init() {
  wireUpload();
  wireSettings();
  const saved = restoreUiState();
  wirePersistence();
  try {
    await Promise.all([loadConfig(), loadFormats()]);
  } catch (error) {
    toast(`Could not load server configuration: ${error.message}`);
  }
  // Theme/model options exist only after loadConfig populated them.
  restoreDynamicChoices(saved);
  pollWorker();
  setInterval(pollWorker, 5000);
  // The model chip and quota note follow the server, not just page load.
  setInterval(loadConfig, 30000);
  refreshDecks().then(() => {
    // Re-open the deck the user was viewing before the reload, if it still exists.
    if (saved && saved.lastDeck && state.decks.some(deck => deck.id === saved.lastDeck)) {
      openDeck(saved.lastDeck);
    }
  });
  resumeInProgress();
  updateGenerateButton();
  updateStages();
}

init();
