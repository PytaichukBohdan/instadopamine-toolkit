import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = await readFile(new URL('../instadna/web/public-worker.js', import.meta.url), 'utf8');
const {default: worker} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const bytes = Uint8Array.from({length: 100}, (_, i) => i);
function run(range, extra = {}, path = '/audio/test.mp3') {
  const headers = {...extra};
  if (range) headers.Range = range;
  return worker.fetch(new Request('https://example.pages.dev' + path, {headers}), {
    ASSETS: {fetch: async () => new Response(bytes, {headers: {
      'Content-Type': 'audio/mpeg', 'Content-Length': '100', 'ETag': '"voice-v1"'
    }})}
  });
}
test('bounded range returns the exact bytes and preserves public security headers', async () => {
  const r = await run('bytes=10-19');
  assert.equal(r.status, 206);
  assert.equal(r.headers.get('content-range'), 'bytes 10-19/100');
  assert.equal(r.headers.get('content-length'), '10');
  assert.equal(r.headers.get('accept-ranges'), 'bytes');
  assert.equal(r.headers.get('x-content-type-options'), 'nosniff');
  assert.deepEqual(new Uint8Array(await r.arrayBuffer()), bytes.slice(10, 20));
});
test('suffix and open-ended requests clamp to the full file', async () => {
  for (const [range, expected] of [['bytes=-4', 'bytes 96-99/100'], ['bytes=98-', 'bytes 98-99/100'], ['bytes=97-999', 'bytes 97-99/100'], ['bytes=-999', 'bytes 0-99/100']]) {
    const r = await run(range); assert.equal(r.status, 206); assert.equal(r.headers.get('content-range'), expected);
  }
});
test('unsatisfiable ranges return 416 and the actual size', async () => {
  for (const range of ['bytes=100-', 'bytes=20-10', 'bytes=-0', 'bytes=999999999999999999999-']) {
    const r = await run(range); assert.equal(r.status, 416); assert.equal(r.headers.get('content-range'), 'bytes */100'); assert.equal((await r.arrayBuffer()).byteLength, 0);
  }
});
test('mismatched If-Range and unsupported multiple ranges return a full representation', async () => {
  for (const [range, headers] of [['bytes=10-19', {'If-Range': '"old"'}], ['bytes=1-2,4-5', {}], ['bytes=', {}]]) {
    const r = await run(range, headers); assert.equal(r.status, 200); assert.equal((await r.arrayBuffer()).byteLength, 100);
  }
});
test('matching If-Range allows a partial response', async () => {
  assert.equal((await run('bytes=10-19', {'If-Range': '"voice-v1"'})).status, 206);
});
test('ordinary downloads and non-audio paths remain full responses', async () => {
  assert.equal((await run(null)).status, 200);
  assert.equal((await run('bytes=10-19', {}, '/index.html')).status, 200);
});
test('Pages ASSETS responses without an internal Content-Length still support seeking', async () => {
  const r = await worker.fetch(new Request('https://example.pages.dev/audio/test.mp3', {
    headers: {Range: 'bytes=10-19'}
  }), {ASSETS: {fetch: async () => new Response(bytes, {headers: {'Content-Type': 'audio/mpeg'}})}});
  assert.equal(r.status, 206);
  assert.equal(r.headers.get('content-range'), 'bytes 10-19/100');
  assert.equal(r.headers.get('content-length'), '10');
  assert.deepEqual(new Uint8Array(await r.arrayBuffer()), bytes.slice(10, 20));
});
