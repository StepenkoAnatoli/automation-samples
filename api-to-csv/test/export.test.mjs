// Offline tests: a fake fetch serves a recorded fixture. No network is used.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { DEFAULT_FIELDS, csvEscape, fetchAllProducts, fetchJson, renderReport, toCsv, validate } from '../lib.mjs';

const fixture = JSON.parse(readFileSync(new URL('./fixture.json', import.meta.url), 'utf8'));
const noSleep = async () => {};
const json = (body, status = 200, headers = {}) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', ...headers } });

/** Fake of dummyjson /products honouring limit, skip and select. `script` can inject failures per call number. */
function fakeApi(products = fixture.products, script = {}) {
  const calls = [];
  const impl = async (url) => {
    calls.push(url);
    const n = calls.length;
    if (script[n]) return script[n](url);
    const u = new URL(url);
    const limit = Number(u.searchParams.get('limit') ?? 30);
    const skip = Number(u.searchParams.get('skip') ?? 0);
    const select = u.searchParams.get('select')?.split(',');
    let page = products.slice(skip, limit === 0 ? undefined : skip + limit);
    if (select) page = page.map((p) => Object.fromEntries(select.filter((k) => k in p).map((k) => [k, p[k]])));
    return json({ products: page, total: products.length, skip, limit });
  };
  return { impl, calls };
}

test('fixture is a real recording of the full catalogue', () => {
  assert.equal(fixture.products.length, fixture.total);
  assert.ok(fixture.total > 100);
});

test('paging: walks limit/skip until every record is received', async () => {
  const api = fakeApi();
  const r = await fetchAllProducts({ fetchImpl: api.impl, pageSize: 30, sleepImpl: noSleep });
  assert.equal(r.products.length, fixture.total);
  assert.equal(r.pages, Math.ceil(fixture.total / 30));
  assert.equal(r.retries, 0);
  assert.deepEqual(api.calls.map((u) => new URL(u).searchParams.get('skip')), Array.from({ length: r.pages }, (_, i) => String(i * 30)));
  assert.deepEqual(r.products.map((p) => p.id), fixture.products.map((p) => p.id));
});

test('paging: exact multiple and tiny page sizes still finish', async () => {
  const items = Array.from({ length: 6 }, (_, i) => ({ id: i + 1, title: `T${i}` }));
  const r = await fetchAllProducts({ fetchImpl: fakeApi(items).impl, pageSize: 3, fields: ['id', 'title'], sleepImpl: noSleep });
  assert.equal(r.pages, 2);
  assert.equal(r.products.length, 6);
});

test('paging: a server that returns an empty page early does not loop forever', async () => {
  const impl = async () => json({ products: [], total: 50, skip: 0, limit: 30 });
  const r = await fetchAllProducts({ fetchImpl: impl, sleepImpl: noSleep });
  assert.equal(r.products.length, 0);
  assert.equal(r.pages, 1);
});

test('field selection: only the chosen fields (plus id) are requested and returned', async () => {
  const api = fakeApi();
  const r = await fetchAllProducts({ fetchImpl: api.impl, fields: ['title', 'price'], sleepImpl: noSleep });
  assert.equal(new URL(api.calls[0]).searchParams.get('select'), 'id,title,price');
  assert.deepEqual(Object.keys(r.products[0]).sort(), ['id', 'price', 'title']);
});

test('retry: 429 then 500 then success; counted and backed off with growing waits', async () => {
  const waits = [];
  const api = fakeApi(fixture.products, {
    1: () => json({}, 429),
    2: () => json({}, 503),
  });
  const r = await fetchAllProducts({ fetchImpl: api.impl, baseDelayMs: 100, sleepImpl: async (ms) => waits.push(ms) });
  assert.equal(r.retries, 2);
  assert.deepEqual(waits, [100, 200]);
  assert.equal(r.products.length, fixture.total);
});

test('retry: Retry-After header is honoured', async () => {
  const waits = [];
  const stats = { retries: 0 };
  const api = fakeApi(fixture.products, { 1: () => json({}, 429, { 'retry-after': '2' }) });
  await fetchJson('https://x/products?limit=1', { fetchImpl: api.impl, sleepImpl: async (ms) => waits.push(ms), stats });
  assert.deepEqual(waits, [2000]);
  assert.equal(stats.retries, 1);
});

test('retry: network errors and timeouts are retried', async () => {
  let n = 0;
  const impl = async () => {
    n++;
    if (n === 1) throw new TypeError('fetch failed');
    if (n === 2) throw Object.assign(new Error('timed out'), { name: 'TimeoutError' });
    return json({ ok: true });
  };
  const stats = { retries: 0 };
  assert.deepEqual(await fetchJson('https://x', { fetchImpl: impl, sleepImpl: noSleep, stats }), { ok: true });
  assert.equal(stats.retries, 2);
});

test('retry: gives up after maxRetries with a clear message', async () => {
  const impl = async () => json({}, 500);
  await assert.rejects(fetchJson('https://x', { fetchImpl: impl, sleepImpl: noSleep, maxRetries: 2 }), /Giving up after 2 retries: HTTP 500/);
});

test('retry: 404 is not retried', async () => {
  let n = 0;
  const impl = async () => { n++; return json({}, 404); };
  await assert.rejects(fetchJson('https://x', { fetchImpl: impl, sleepImpl: noSleep }), /HTTP 404/);
  assert.equal(n, 1);
});

test('timeout: every request carries an abort signal', async () => {
  let signal;
  const impl = async (_url, opts) => { signal = opts.signal; return json({ ok: 1 }); };
  await fetchJson('https://x', { fetchImpl: impl, timeoutMs: 1234 });
  assert.ok(signal instanceof AbortSignal);
});

test('CSV escaping: commas, quotes, newlines, accents, Hebrew, arrays, empties', () => {
  assert.equal(csvEscape('plain'), 'plain');
  assert.equal(csvEscape('a,b'), '"a,b"');
  assert.equal(csvEscape('say "hi"'), '"say ""hi"""');
  assert.equal(csvEscape('line1\nline2'), '"line1\nline2"');
  assert.equal(csvEscape('line1\r\nline2'), '"line1\r\nline2"');
  assert.equal(csvEscape('café שלום'), 'café שלום');
  assert.equal(csvEscape(['a', 'b']), 'a|b');
  assert.equal(csvEscape(null), '');
  assert.equal(csvEscape(undefined), '');
  assert.equal(csvEscape(0), '0');
});

test('CSV file: header + rows, CRLF, and a quoted multi-line value stays one record', () => {
  const rows = [{ id: 1, title: 'A "big", bold\nthing', price: 9.5 }, { id: 2, title: 'Crème brûlée שלום', price: 3 }];
  const csv = toCsv(['id', 'title', 'price'], rows);
  assert.equal(csv, 'id,title,price\r\n1,"A ""big"", bold\nthing",9.5\r\n2,Crème brûlée שלום,3\r\n');
});

test('CSV file written with a BOM decodes back with accents and Hebrew intact', () => {
  const bytes = Buffer.from('﻿' + toCsv(['t'], [{ t: 'é שלום' }]), 'utf8');
  assert.deepEqual([...bytes.subarray(0, 3)], [0xef, 0xbb, 0xbf]);
  assert.equal(new TextDecoder('utf-8', { ignoreBOM: false }).decode(bytes), 'é שלום'.padStart(0) && 't\r\né שלום\r\n');
});

test('validation: skips missing id, missing title, duplicate id, and says why', () => {
  const { rows, skipped } = validate(
    [{ id: 1, title: 'ok' }, { title: 'no id' }, { id: 2, title: '  ' }, { id: 1, title: 'again' }, { id: 3, title: 'fine' }],
    ['id', 'title'],
  );
  assert.deepEqual(rows.map((r) => r.id), [1, 3]);
  assert.deepEqual(skipped.map((s) => s.reason), ['missing id', 'missing title', 'duplicate id']);
});

test('report: counts match the data', async () => {
  const dirty = [...fixture.products.slice(0, 60), { id: 9999, title: '' }, fixture.products[0]];
  const api = fakeApi(dirty, { 2: () => json({}, 429) });
  const r = await fetchAllProducts({ fetchImpl: api.impl, pageSize: 30, sleepImpl: noSleep });
  const { rows, skipped } = validate(r.products, DEFAULT_FIELDS);
  const csv = toCsv(DEFAULT_FIELDS, rows);
  const report = renderReport({
    date: '2026-01-01', source: 'fake', pageSize: 30, fetched: r.products.length, total: r.total, pages: r.pages,
    retries: r.retries, fields: DEFAULT_FIELDS, rowsWritten: rows.length, skipped, seconds: 1.234,
  });
  assert.equal(r.products.length, 62);
  assert.equal(rows.length, 60);
  assert.equal(skipped.length, 2);
  assert.equal(r.pages, 3);
  assert.equal(r.retries, 1);
  assert.match(report, /Records fetched: 62 \(the API reports 62 in total\)/);
  assert.match(report, /Pages requested: 3 /);
  assert.match(report, /Retries: 1\n/);
  assert.match(report, /Rows written to `products.csv`: 60/);
  assert.match(report, /Rows skipped: 2\n {2}- missing title: 1\n {2}- duplicate id: 1/);
  assert.match(report, /Run time: 1\.2 seconds/);
  assert.equal(csv.split('\r\n').length - 2, rows.length); // minus header and trailing newline (tags have no newlines)
});

test('end to end against the fixture: every record becomes one row', async () => {
  const r = await fetchAllProducts({ fetchImpl: fakeApi().impl, sleepImpl: noSleep });
  const { rows, skipped } = validate(r.products, DEFAULT_FIELDS);
  assert.equal(rows.length, fixture.total);
  assert.equal(skipped.length, 0);
});

test('timeout: a request that never answers is aborted, retried, then reported', async () => {
  let calls = 0;
  const hang = (_url, { signal }) => new Promise((_, reject) => {
    calls++;
    signal.addEventListener('abort', () => reject(signal.reason));
  });
  await assert.rejects(fetchJson('https://x', { fetchImpl: hang, timeoutMs: 20, maxRetries: 1, sleepImpl: noSleep }), /Giving up after 1 retries: Timeout after 20 ms/);
  assert.equal(calls, 2);
});
