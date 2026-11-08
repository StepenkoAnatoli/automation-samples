// Core logic for api-to-csv. No dependencies: built-in fetch only.

export const DEFAULT_FIELDS = ['id', 'title', 'brand', 'category', 'price', 'rating', 'stock', 'sku', 'tags'];

/** Quote one CSV value (RFC 4180): wrap in quotes when it holds , " CR or LF; double inner quotes. */
export function csvEscape(value) {
  if (value === null || value === undefined) return '';
  let s = Array.isArray(value) ? value.join('|') : typeof value === 'object' ? JSON.stringify(value) : String(value);
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCsv(fields, rows) {
  const lines = [fields.map(csvEscape).join(',')];
  for (const r of rows) lines.push(fields.map((f) => csvEscape(r[f])).join(','));
  return lines.join('\r\n') + '\r\n';
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * GET a URL with a timeout; retry on 429, 5xx, timeouts and network errors with
 * exponential backoff (honours Retry-After). Other 4xx fail immediately.
 * stats.retries is incremented for every retry.
 */
export async function fetchJson(url, { fetchImpl = fetch, timeoutMs = 10000, maxRetries = 4, baseDelayMs = 500, stats = { retries: 0 }, sleepImpl = sleep } = {}) {
  let lastErr;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    let retryAfterMs = null;
    try {
      const res = await fetchImpl(url, { signal: AbortSignal.timeout(timeoutMs), headers: { accept: 'application/json' } });
      if (res.ok) return await res.json();
      const retryable = res.status === 429 || res.status >= 500;
      lastErr = new Error(`HTTP ${res.status} for ${url}`);
      if (!retryable) throw Object.assign(lastErr, { fatal: true });
      const ra = Number(res.headers?.get?.('retry-after'));
      if (Number.isFinite(ra) && ra > 0) retryAfterMs = ra * 1000;
    } catch (e) {
      if (e.fatal) throw e;
      lastErr = e.name === 'TimeoutError' ? new Error(`Timeout after ${timeoutMs} ms for ${url}`) : e;
    }
    if (attempt < maxRetries) {
      stats.retries++;
      await sleepImpl(retryAfterMs ?? baseDelayMs * 2 ** attempt);
    }
  }
  throw new Error(`Giving up after ${maxRetries} retries: ${lastErr.message}`);
}

/** Fetch every page of /products using limit/skip until `total` is reached. */
export async function fetchAllProducts({ baseUrl = 'https://dummyjson.com', pageSize = 30, fields = DEFAULT_FIELDS, maxPages = Infinity, ...opts } = {}) {
  const stats = opts.stats ?? { retries: 0 };
  const products = [];
  let skip = 0;
  let total = Infinity;
  let pages = 0;
  let firstPage = null;
  while (skip < total && pages < maxPages) {
    // `select` limits the payload server-side; id is always needed to spot duplicates.
    const select = [...new Set(['id', ...fields])].join(',');
    const url = `${baseUrl}/products?limit=${pageSize}&skip=${skip}&select=${select}`;
    const body = await fetchJson(url, { ...opts, stats });
    if (!Array.isArray(body.products)) throw new Error(`Unexpected response at skip=${skip}: no "products" array`);
    pages++;
    firstPage ??= body;
    total = body.total;
    products.push(...body.products);
    if (body.products.length === 0) break; // safety: never loop forever
    skip += body.products.length;
  }
  return { products, total, pages, retries: stats.retries, firstPage };
}

/** Drop records that cannot be used and say why. A record needs an id and a title. */
export function validate(products, fields) {
  const rows = [];
  const skipped = [];
  const seen = new Set();
  for (const p of products) {
    if (p?.id === undefined || p?.id === null) { skipped.push({ id: '', reason: 'missing id' }); continue; }
    if (seen.has(p.id)) { skipped.push({ id: p.id, reason: 'duplicate id' }); continue; }
    if (fields.includes('title') && !String(p.title ?? '').trim()) { skipped.push({ id: p.id, reason: 'missing title' }); continue; }
    seen.add(p.id);
    rows.push(p);
  }
  return { rows, skipped };
}

export function renderReport({ date, source, pageSize, fetched, total, pages, retries, fields, rowsWritten, skipped, seconds }) {
  const byReason = {};
  for (const s of skipped) byReason[s.reason] = (byReason[s.reason] ?? 0) + 1;
  const skipLines = Object.keys(byReason).length
    ? Object.entries(byReason).map(([r, n]) => `  - ${r}: ${n}`).join('\n')
    : '  - none';
  return `# Product export: run report

- Run date: ${date}
- Source: ${source}
- Records fetched: ${fetched} (the API reports ${total} in total)
- Pages requested: ${pages} (${pageSize} per page, using limit and skip)
- Retries: ${retries}
- Extra request: 1 (the raw first page, saved unfiltered in \`before/first-page.json\`)
- Fields exported (${fields.length}): ${fields.join(', ')}
- Rows written to \`products.csv\`: ${rowsWritten}
- Rows skipped: ${skipped.length}
${skipLines}
- Run time: ${seconds.toFixed(1)} seconds

## How it works

1. Pages are requested one after another until every record the API reports has been received.
2. Each request has a timeout. Rate-limit (429), server (5xx) and network failures are retried with
   growing waits; other errors stop the run with a clear message.
3. Only the chosen fields are requested and written. List fields (such as tags) are joined with \`|\`.
4. The file is UTF-8 with a byte-order mark so Excel shows accents and Hebrew correctly. Values with
   commas, quotes or line breaks are quoted.
5. A record without an id or title, or a repeated id, is skipped and counted above.
`;
}
