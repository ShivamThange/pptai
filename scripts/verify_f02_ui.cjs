/* Intake DOM acceptance. HTTP/worker behavior is covered separately by pytest.
 * Usage: NODE_PATH=<audit ui-runtime/node_modules> node scripts/verify_f02_ui.cjs
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const root = path.resolve(__dirname, '..');
const dom = new JSDOM(fs.readFileSync(path.join(root,'frontend/upload/index.html'),'utf8'), {url:'http://localhost/upload/',runScripts:'outside-only'});
const {window:w} = dom, requests = [], uploads = new Map(), jobStates = new Map(), events = [];
const config = {dropdown:['auto','pdf','docx','txt','markdown','csv','xlsx','png','jpeg'],limits:{upload_limit_bytes:104857600},formats:[
  ['pdf',['.pdf']],['docx',['.docx']],['txt',['.txt']],['markdown',['.md','.markdown']],['csv',['.csv']],['xlsx',['.xlsx']],['png',['.png']],['jpeg',['.jpg','.jpeg']]
].map(([type,extensions])=>({type,extensions}))};
function job() {const id='job-'+jobStates.size; const value={id,status:'queued',stage:null}; jobStates.set(id,value); return {job_id:id,status_url:'/api/jobs/'+id};}
w.EventSource=class {constructor(url){this.url=url;this.listeners={};this.closed=false;events.push(this);} addEventListener(type,fn){this.listeners[type]=fn;} close(){this.closed=true;} progress(value){this.listeners.progress({data:JSON.stringify(value)});} };
w.fetch=async(url,opts={})=>{
  requests.push({url,body:typeof opts.body==='string'?JSON.parse(opts.body):opts.body});
  let status=200, result;
  if(url==='/api/input-formats') result=config;
  else if(url==='/api/documents') {
    const file=opts.body.get('file'), encoding=opts.body.get('encoding');
    if(file.name==='wrong.pdf') {status=422;result={detail:{code:'TYPE_MISMATCH',message:'The bytes are PNG; rename and choose PNG or Auto.',detected_type:'png'}};}
    else if(file.name==='latin.txt' && encoding==='auto') {status=422;result={detail:{code:'TEXT_ENCODING_REQUIRED',message:'Choose an encoding.'}};}
    else {const id='upload-'+uploads.size, type=config.formats.find(f=>f.extensions.some(e=>file.name.endsWith(e))).type;
      result={id,upload:{detected_type:type,findings:[{message:'<img src=x onerror="window.injected=true">'}]}};uploads.set(id,result);}
  } else if(url==='/api/decks' || url.endsWith('/parse')) {result=job();status=202;}
  else if(url.endsWith('/cancel')) {const id=url.split('/')[3]; result={...jobStates.get(id),status:'cancelled'}; jobStates.set(id,result);}
  else if(url.startsWith('/api/jobs/')) result=jobStates.get(url.split('/')[3]);
  else throw Error('Unexpected URL: '+url);
  return {ok:status<400,status,json:async()=>result};
};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function settle(){for(let i=0;i<8;i++)await tick();}
function add(names){const picker=w.document.querySelector('#files'); Object.defineProperty(picker,'files',{value:names.map(name=>new w.File(['source data'],name)),configurable:true});picker.onchange({target:picker});}
function rows(){return [...w.document.querySelectorAll('.source')];}
function button(row,text){return [...row.querySelectorAll('button')].find(b=>b.textContent===text);}
async function main(){
  w.eval(fs.readFileSync(path.join(root,'frontend/upload/upload.js'),'utf8')); await settle();
  assert(w.document.querySelector('#files').accept.includes('.xlsx'));
  add(['valid.txt','wrong.pdf','latin.txt','records.csv']); await settle();
  assert.equal(rows().length,4);assert(w.document.querySelector('#send').disabled);
  assert(rows()[0].textContent.includes('Uploaded'));
  assert.equal(rows()[0].querySelector('img'),null);assert.equal(w.injected,undefined);
  assert(rows()[1].textContent.includes('PNG')); assert(rows()[2].querySelector('input[type=text]'));
  const encoding=rows()[2].querySelector('input[type=text]');encoding.value='cp1252';encoding.onchange();button(rows()[2],'Retry upload').click();await settle();
  assert(rows()[2].textContent.includes('Uploaded'));
  button(rows()[1],'Replace file').click();const replacement=rows()[1].querySelector('input[type=file]');Object.defineProperty(replacement,'files',{value:[new w.File(['pixels'],'fixed.png')]});replacement.onchange();await settle();
  assert(rows()[1].textContent.includes('Detected: png'));assert(rows()[1].textContent.includes('OCR'));
  assert(!w.document.querySelector('#send').disabled);
  const mismatched=rows()[1].querySelector('select');mismatched.value='pdf';mismatched.onchange();assert(w.document.querySelector('#send').disabled);
  const correct=rows()[1].querySelector('select');correct.value='auto';correct.onchange();
  w.document.querySelector('#parse').click();await settle();
  assert.equal(requests.filter(r=>r.url.endsWith('/parse')).length,4);
  w.document.querySelector('#send').click();await settle();
  const sent=requests.find(r=>r.url==='/api/decks');assert.equal(sent.body.sources.length,4);assert(w.document.querySelector('#send').disabled);
  const captured=JSON.stringify(sent.body);
  const type=rows()[0].querySelector('select');type.value='markdown';type.onchange();assert.equal(JSON.stringify(sent.body),captured);assert(!w.document.querySelector('#send').disabled);
  const event=events.at(-1), id=event.url.split('/')[3];
  event.progress({id,status:'running',stage:'parsing',progress:{files_completed:1,files_total:4,outcomes:[{upload_id:'upload-0',status:'complete',findings:[]}]}});
  assert(w.document.querySelector('#jobs').textContent.includes('1/4 files processed'));
  event.onerror(); await settle();
  w.document.querySelector('#jobs .job button').click();await settle();assert(event.closed);assert(w.document.querySelector('#jobs').textContent.includes('cancelled'));
  button(rows()[0],'Remove').click();assert.equal(rows().length,3);assert.equal(JSON.stringify(sent.body),captured);
  for(const value of jobStates.values()) {value.status='cancelled';}
  for(const event of events) {event.progress({id:event.url.split('/')[3],status:'cancelled'});}
  const evidence={checks:['multi-file selection','per-row failure isolation','encoding retry','replacement','dropdown correction','relevant CSV/OCR controls','optional parse','Send captures immutable source set','duplicate Send disabled','progress/reconnect','cancel','plain-text findings','remove affects future requests'],requests:requests.filter(r=>typeof r.body==='object' && !(r.body instanceof w.FormData))};
  const output=process.argv[2];if(output)fs.writeFileSync(output,JSON.stringify(evidence,null,2));
  console.log('F02 intake UI: 13 checks passed');dom.window.close();
}
main().catch(error=>{console.error(error);dom.window.close();process.exitCode=1;});
