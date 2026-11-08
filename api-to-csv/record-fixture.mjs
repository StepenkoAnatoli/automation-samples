// Re-records test/fixture.json from the live API (the tests themselves never touch the network).
// Usage: node record-fixture.mjs
import { writeFile } from 'node:fs/promises';
import { DEFAULT_FIELDS } from './lib.mjs';

const select = DEFAULT_FIELDS.join(',');
const res = await fetch(`https://dummyjson.com/products?limit=0&select=${select}`);
if (!res.ok) throw new Error(`HTTP ${res.status}`);
const body = await res.json();
await writeFile(new URL('./test/fixture.json', import.meta.url), JSON.stringify({ recorded: new Date().toISOString().slice(0, 10), total: body.total, products: body.products }, null, 1) + '\n');
console.log(`recorded ${body.products.length} of ${body.total}`);
