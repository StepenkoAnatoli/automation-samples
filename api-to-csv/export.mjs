#!/usr/bin/env node
// Usage: node export.mjs [--fields id,title,price] [--page-size 30] [--out after] [--dry-run]
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { DEFAULT_FIELDS, fetchAllProducts, fetchJson, renderReport, toCsv, validate } from './lib.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const { values } = parseArgs({
  options: {
    fields: { type: 'string', default: DEFAULT_FIELDS.join(',') },
    'page-size': { type: 'string', default: '30' },
    out: { type: 'string', default: join(here, 'after') },
    before: { type: 'string', default: join(here, 'before') },
    base: { type: 'string', default: 'https://dummyjson.com' },
    timeout: { type: 'string', default: '10000' },
    'dry-run': { type: 'boolean', default: false },
  },
});

const fields = values.fields.split(',').map((f) => f.trim()).filter(Boolean);
const pageSize = Number(values['page-size']);
const started = performance.now();
const dryRun = values['dry-run'];

try {
  if (dryRun) {
    // Dry run: one request for the first page to show what the full run would do. Nothing is written.
    const r = await fetchAllProducts({ baseUrl: values.base, pageSize, fields, timeoutMs: Number(values.timeout), maxRetries: 2, maxPages: 1 });
    console.log(`DRY RUN: nothing written.
The API reports ${r.total} products; a full run would make ${Math.ceil(r.total / pageSize)} requests of ${pageSize}.
Fields: ${fields.join(', ')}
First row: ${JSON.stringify(r.products[0])}`);
    process.exit(0);
  }
  const result = await fetchAllProducts({ baseUrl: values.base, pageSize, fields, timeoutMs: Number(values.timeout) });
  const { rows, skipped } = validate(result.products, fields);
  await mkdir(values.out, { recursive: true });
  await mkdir(values.before, { recursive: true });
  // The "before": the raw, unfiltered first page, exactly as the API sends it.
  const raw = await fetchJson(`${values.base}/products?limit=${pageSize}&skip=0`, { timeoutMs: Number(values.timeout) });
  await writeFile(join(values.before, 'first-page.json'), JSON.stringify(raw, null, 2) + '\n');
  await writeFile(join(values.out, 'products.csv'), '﻿' + toCsv(fields, rows), 'utf8');
  const report = renderReport({
    date: new Date().toISOString().slice(0, 10), source: `${values.base}/products`, pageSize,
    fetched: result.products.length, total: result.total, pages: result.pages, retries: result.retries,
    fields, rowsWritten: rows.length, skipped, seconds: (performance.now() - started) / 1000,
  });
  await writeFile(join(values.out, 'REPORT.md'), report, 'utf8');
  console.log(report);
} catch (e) {
  console.error(`Error: ${e.message}`);
  process.exit(1);
}
