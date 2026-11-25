import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../instadna/web/_worker.js', import.meta.url),'utf8');
const {default:worker} = await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const env = {REPORT_USERNAME:'test',REPORT_PASSWORD:'test-only:password',ASSETS:{fetch:async()=>new Response('private content')}};
const request=(path,credentials)=>new Request('https://report.pages.dev'+path,{headers:credentials?{Authorization:'Basic '+btoa(credentials)}:{}});
test('every path, including static assets, requires authentication',async()=>{
  for(const path of ['/','/style.css','/search-index.json','/sources/post.html','/unknown','/_worker.js']){
    const r=await worker.fetch(request(path),env);assert.equal(r.status,401);assert.match(r.headers.get('WWW-Authenticate'),/Basic/);assert.doesNotMatch(await r.text(),/private content/);
  }
});
test('missing secrets fail closed before serving assets',async()=>{
  const r=await worker.fetch(request('/','test:test-only:password'),{ASSETS:env.ASSETS});assert.equal(r.status,503);
});
test('valid authentication serves content with private no-store headers',async()=>{
  const r=await worker.fetch(request('/search-index.json','test:test-only:password'),env);assert.equal(r.status,200);assert.equal(await r.text(),'private content');assert.match(r.headers.get('Cache-Control'),/no-store/);
});
test('wrong or malformed credentials never authorize',async()=>{
  assert.equal((await worker.fetch(request('/','test:wrong'),env)).status,401);
  const r=new Request('https://report.pages.dev',{headers:{Authorization:'Basic !!!'}});assert.equal((await worker.fetch(r,env)).status,401);
});
test('authenticated audio and video support byte ranges; anonymous range requests are still refused',async()=>{
  const bytes=Uint8Array.from({length:100},(_,i)=>i);
  const audioEnv={...env,ASSETS:{fetch:async()=>new Response(bytes,{headers:{'Content-Type':'audio/mpeg'}})}};
  const ranged=(credentials)=>new Request('https://report.pages.dev/audio/self-presentation-60s.mp3',{headers:{Range:'bytes=10-19',...(credentials?{Authorization:'Basic '+btoa(credentials)}:{})}});
  const r=await worker.fetch(ranged('test:test-only:password'),audioEnv);
  assert.equal(r.status,206);assert.equal(r.headers.get('Content-Range'),'bytes 10-19/100');assert.match(r.headers.get('Cache-Control'),/no-store/);
  assert.deepEqual(new Uint8Array(await r.arrayBuffer()),bytes.slice(10,20));
  const anon=await worker.fetch(ranged(null),audioEnv);assert.equal(anon.status,401);assert.equal((await anon.arrayBuffer()).byteLength>0,true);
  const page=await worker.fetch(new Request('https://report.pages.dev/index.html',{headers:{Range:'bytes=0-1',Authorization:'Basic '+btoa('test:test-only:password')}}),env);
  assert.equal(page.status,200);
  const video=await worker.fetch(new Request('https://report.pages.dev/video/self-presentation-edit.mp4',{headers:{Range:'bytes=0-9',Authorization:'Basic '+btoa('test:test-only:password')}}),audioEnv);
  assert.equal(video.status,206);assert.equal(video.headers.get('Content-Range'),'bytes 0-9/100');
  const anonVideo=await worker.fetch(new Request('https://report.pages.dev/video/self-presentation-edit.mp4',{headers:{Range:'bytes=0-9'}}),audioEnv);assert.equal(anonVideo.status,401);
});
const publicSource = await readFile(new URL('../instadna/web/public-worker.js', import.meta.url),'utf8');
const {default:publicWorker} = await import('data:text/javascript;base64,'+Buffer.from(publicSource).toString('base64'));
test('explicit public edition serves pages and assets without a login challenge',async()=>{
  for (const path of ['/','/search-index.json','/sources/post.html']) {
    const r=await publicWorker.fetch(request(path),{ASSETS:{fetch:async()=>new Response('public content')}});
    assert.equal(r.status,200);assert.equal(r.headers.get('WWW-Authenticate'),null);
    assert.equal(await r.text(),'public content');assert.equal(r.headers.get('X-Content-Type-Options'),'nosniff');
  }
});

test('protected audio ranges authenticate before reading even one source byte',async()=>{
  let fetched=0;
  const rangeEnv={...env,ASSETS:{fetch:async()=>{fetched++;return new Response(Uint8Array.from({length:100},(_,i)=>i),{headers:{'Content-Type':'audio/mpeg'}});}}};
  for (const credentials of [null,'test:wrong']) {
    const r=request('/audio/phrase-test.mp3',credentials);r.headers.set('Range','bytes=10-19');
    assert.equal((await worker.fetch(r,rangeEnv)).status,401);
  }
  assert.equal(fetched,0);
  const r=request('/audio/phrase-test.mp3','test:test-only:password');r.headers.set('Range','bytes=10-19');
  const response=await worker.fetch(r,rangeEnv);
  assert.equal(response.status,206);assert.equal(response.headers.get('Content-Range'),'bytes 10-19/100');
  assert.match(response.headers.get('Cache-Control'),/private, no-store/);
  assert.deepEqual(new Uint8Array(await response.arrayBuffer()),Uint8Array.from({length:10},(_,i)=>i+10));
  r.headers.set('Range','bytes=100-');assert.equal((await worker.fetch(r,rangeEnv)).status,416);
});

test('standalone protected and public workers share the same tested range implementation',()=>{
  const extract=s=>s.slice(s.indexOf('export async function audioRangeResponse'),s.indexOf('\n}\n',s.indexOf('export async function audioRangeResponse'))+3);
  assert.equal(extract(source),extract(publicSource));
});
