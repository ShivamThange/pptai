'use strict';
const rows = [], jobs = new Map();
let formats, sending = false, lastSubmission = '';
const el = (tag, text, cls) => {const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node;};
async function api(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {const detail = data.detail; throw {code: detail?.code || 'REQUEST_FAILED', message: detail?.message || (typeof detail === 'string' ? detail : JSON.stringify(detail)), detected_type: detail?.detected_type};}
  return data;
}
function control(label, node) {const box = el('label', label, 'control'); box.append(node); return box;}
function select(values, current) {const node = el('select'); for (const value of values) {const option = el('option', value === 'auto' ? 'Auto-detect' : value === '\t' ? 'Tab' : value); option.value = value; node.append(option);} node.value = current; return node;}
function options(row) {const value = {encoding: row.encoding || 'auto'}; if (['pdf', 'png', 'jpeg'].includes(row.kind)) value.ocr = row.ocr; if (row.kind === 'csv') {value.csv_delimiter = row.delimiter; value.csv_has_header = row.header;} if (!['txt', 'markdown', 'csv'].includes(row.kind)) delete value.encoding; return value;}
function sources() {return rows.filter(r => !r.removed).map(r => ({document_id: r.upload?.id, selected_type: r.type, parse_options: options(r)}));}
function ready(row) {return row.upload && !row.busy && !row.error && (!row.detected || ['txt','markdown','csv'].includes(row.detected) || row.type === 'auto' || row.type === row.detected);}
function buttons() {const included = rows.filter(r => !r.removed); const ok = included.length && included.every(ready); document.querySelector('#parse').disabled = sending || !ok; document.querySelector('#send').disabled = sending || !ok || JSON.stringify(sources()) === lastSubmission;}
function render(row) {
  row.node.replaceChildren();
  row.kind = row.type === 'auto' ? row.detected || formats.formats.find(f => f.extensions.some(e => row.file.name.toLowerCase().endsWith(e)))?.type : row.type;
  row.node.append(el('h2', row.file.name), el('p', `${row.file.size.toLocaleString()} bytes · ${row.detected ? `Detected: ${row.detected}` : 'Awaiting detection'}`, 'muted'));
  const controls = el('div', undefined, 'controls'), type = select(formats.dropdown, row.type);
  type.onchange = () => {row.type = type.value; render(row);}; controls.append(control('File type', type));
  if (['txt', 'markdown', 'csv'].includes(row.kind) || row.error?.code === 'TEXT_ENCODING_REQUIRED') {const encoding = el('input'); encoding.type = 'text'; encoding.value = row.encoding; encoding.placeholder = 'auto / windows-1252'; encoding.onchange = () => {row.encoding = encoding.value.trim() || 'auto'; buttons();}; controls.append(control('Text encoding', encoding));}
  if (['pdf', 'png', 'jpeg'].includes(row.kind)) {const ocr = select(['auto','off','force'], row.ocr); ocr.onchange = () => {row.ocr = ocr.value; buttons();}; controls.append(control('OCR', ocr));}
  if (row.kind === 'csv') {const delimiter = select(['auto', ',', ';', '\t', '|'], row.delimiter); delimiter.onchange = () => {row.delimiter = delimiter.value; buttons();}; controls.append(control('CSV delimiter', delimiter)); const header = el('input'); header.type = 'checkbox'; header.checked = row.header; header.onchange = () => {row.header = header.checked; buttons();}; controls.append(control('First record is header', header));}
  const retry = el('button', row.busy ? 'Uploading…' : row.upload ? 'Upload again' : 'Retry upload'); retry.disabled = row.busy; retry.onclick = () => upload(row); controls.append(retry);
  const replace = el('button', 'Replace file'); const replacement = el('input'); replacement.type = 'file'; replacement.hidden = true; replacement.accept = formats.formats.flatMap(f => f.extensions).join(','); replacement.onchange = () => {if (replacement.files[0]) {row.file = replacement.files[0]; row.type = 'auto'; row.upload = null; row.detected = null; upload(row);}}; replace.onclick = () => replacement.click(); replace.disabled = row.busy; controls.append(replace, replacement);
  const remove = el('button','Remove'); remove.onclick = () => {row.removed = true; row.node.remove(); buttons();}; controls.append(remove); row.node.append(controls);
  row.node.append(el('p', row.busy ? 'Uploading' : row.error ? row.error.message : row.upload ? 'Uploaded' : 'Ready to upload', row.error ? 'findings error' : 'state'));
  if (row.upload?.upload?.findings.length) row.node.append(el('p', row.upload.upload.findings.map(f => f.message).join('\n'), 'findings'));
  if (row.upload && !ready(row) && !row.busy && !row.error) row.node.append(el('p', `Choose ${row.detected} or Auto-detect before sending.`, 'error'));
  buttons();
}
async function upload(row) {
  row.busy = true; row.error = null; render(row);
  const form = new FormData(); form.append('file', row.file); form.append('selected_type', row.type); form.append('encoding', row.encoding);
  try {row.upload = await api('/api/documents', {method:'POST',body:form}); row.detected = row.upload.upload.detected_type;} catch(error) {row.error = error; row.detected = error.detected_type || row.detected;}
  row.busy = false; if (!row.removed) render(row);
}
function follow(submitted) {
  if (jobs.has(submitted.job_id)) return;
  const panel = el('article',undefined,'job'), title = el('h2',`Job ${submitted.job_id}`), status = el('pre'), cancel = el('button','Cancel'); panel.append(title,status,cancel); document.querySelector('#jobs').prepend(panel);
  const state = {events:null, timer:null, terminal:false}; jobs.set(submitted.job_id,state);
  cancel.onclick = () => api(submitted.status_url + '/cancel', {method:'POST'}).then(update).catch(error => status.textContent = error.message);
  function update(job) {
    const progress = job.progress || {};
    status.textContent = `${job.status} · ${job.stage || 'Waiting for worker'}\n${progress.files_completed === undefined ? '' : `${progress.files_completed}/${progress.files_total} files processed\n`}${job.error?.message || ''}`;
    for (const result of progress.outcomes || job.result?.sources || []) {status.textContent += `\n${result.upload_id || result.document_id}: ${result.status}\n${(result.findings || []).map(f => f.message).join('\n')}`;}
    if (job.result?.pptx_url && !panel.querySelector('a')) {const link = el('a','Download presentation'); link.href = job.result.pptx_url; panel.append(link);}
    if (['completed','failed','cancelled'].includes(job.status)) {state.terminal = true; state.events?.close(); clearTimeout(state.timer); cancel.disabled = true;}
  }
  async function poll() {try {update(await api(submitted.status_url));} catch(error) {status.textContent = error.message;} if (!state.terminal) state.timer = setTimeout(poll, 2000);}
  state.events = new EventSource(submitted.status_url + '/events'); state.events.addEventListener('progress', event => update(JSON.parse(event.data))); state.events.onerror = () => {if (!state.timer && !state.terminal) poll();}; poll();
}
document.querySelector('#files').onchange = event => {for (const file of event.target.files) {const row = {file,type:'auto',encoding:'auto',ocr:'auto',delimiter:'auto',header:true,node:el('article',undefined,'source')}; rows.push(row); document.querySelector('#rows').append(row.node); upload(row);} event.target.value = '';};
document.querySelector('#parse').onclick = async () => {sending = true; buttons(); const snapshot = sources(); try {for (const source of snapshot) follow(await api(`/api/documents/${source.document_id}/parse`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({selected_type:source.selected_type,parse_options:source.parse_options})}));} catch(error) {document.querySelector('#message').textContent = error.message;} finally {sending = false; buttons();}};
document.querySelector('#send').onclick = async () => {sending = true; buttons(); const snapshot = sources(); try {follow(await api('/api/decks', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sources:snapshot, asset_options:{mode:'structured',semantic_understanding:'auto'}})})); lastSubmission = JSON.stringify(snapshot); document.querySelector('#message').textContent = 'Source set captured. You can change rows for your next presentation.';} catch(error) {document.querySelector('#message').textContent = error.message;} finally {sending = false; buttons();}};
document.querySelector('#files').disabled = true;
api('/api/input-formats').then(data => {formats = data; document.querySelector('#files').accept = data.formats.flatMap(f => f.extensions).join(','); document.querySelector('#files').disabled = false; const caps = [`${(data.limits.upload_limit_bytes / 1048576).toLocaleString()} MiB per file`]; if (data.limits.max_source_files) caps.push(`${data.limits.max_source_files} files per submission`); if (data.limits.max_source_bytes) caps.push(`${(data.limits.max_source_bytes / 1048576).toLocaleString()} MiB per source set`); if (data.limits.max_source_pages) caps.push(`${data.limits.max_source_pages} pages per PDF`); if (data.limits.max_workbook_cells) caps.push(`${data.limits.max_workbook_cells.toLocaleString()} cells per workbook`); document.querySelector('#limits').textContent = `Limits: ${caps.join(' � ')}. Supported: ${data.formats.map(f => f.type.toUpperCase()).join(', ')}.`;}).catch(error => document.querySelector('#limits').textContent = error.message);
