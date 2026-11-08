import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import worker, { localeForCountry } from '../server/worker.mjs';

function requestWithCountry(country, init = {}, url = 'https://film-lab.example/api/locale') {
  const request = new Request(url, init);
  if (country !== undefined) Object.defineProperty(request, 'cf', { value: { country } });
  return request;
}

test('Korean connections receive Korean and other detected countries receive English', async () => {
  for (const [country, locale] of [['KR', 'ko'], ['US', 'en'], ['JP', 'en'], ['DE', 'en'], ['KP', 'en']]) {
    const response = await worker.fetch(requestWithCountry(country), {});
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { locale });
    assert.equal(response.headers.get('Cache-Control'), 'no-store');
    assert.match(response.headers.get('Content-Type'), /^application\/json/);
    assert.equal(response.headers.get('Set-Cookie'), null);
  }
});

test('unknown geography returns null for client fallback without guessing from a request header', async () => {
  for (const country of [undefined, null, '', 'XX', 'T1', 'kr', 'KOR', 82]) {
    assert.equal(localeForCountry(country), null);
    const response = await worker.fetch(requestWithCountry(country, { headers: { 'CF-IPCountry': 'KR', 'Accept-Language': 'ko-KR' } }), {});
    assert.deepEqual(await response.json(), { locale: null });
  }
});

test('trusted edge country takes precedence over caller-supplied headers and query parameters', async () => {
  const request = requestWithCountry('US', { headers: { 'CF-IPCountry': 'KR', 'Accept-Language': 'ko' } }, 'https://film-lab.example/api/locale?country=KR&locale=ko');
  assert.deepEqual(await (await worker.fetch(request, {})).json(), { locale: 'en' });
});

test('the locale endpoint accepts only read-only GET and HEAD', async () => {
  const head = await worker.fetch(requestWithCountry('KR', { method: 'HEAD' }), {});
  assert.equal(head.status, 200);
  assert.equal(await head.text(), '');
  assert.equal(head.headers.get('Cache-Control'), 'no-store');
  for (const method of ['POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']) {
    const response = await worker.fetch(requestWithCountry('KR', { method }), {});
    assert.equal(response.status, 405);
    assert.equal(response.headers.get('Allow'), 'GET, HEAD');
    assert.equal(response.headers.get('Cache-Control'), 'no-store');
  }
});

test('other routes fall through to static assets without response or request mutation', async () => {
  for (const pathname of ['/', '/catalog.json', '/assets/index-hash.js', '/api/locale/extra', '/api/locale/']) {
    const request = requestWithCountry('KR', {}, `https://film-lab.example${pathname}`);
    const assetResponse = new Response('static asset', { headers: { ETag: 'sample-etag' } });
    const response = await worker.fetch(request, { ASSETS: { fetch: actual => { assert.equal(actual, request); return assetResponse; } } });
    assert.equal(response, assetResponse);
    assert.equal(response.headers.get('ETag'), 'sample-etag');
  }
});

test('Wrangler invokes the Worker first only for locale lookup and keeps static asset routing', async () => {
  const configuration = JSON.parse(await fs.readFile(new URL('../wrangler.jsonc', import.meta.url), 'utf8'));
  assert.equal(configuration.main, 'server/worker.mjs');
  assert.equal(configuration.assets.binding, 'ASSETS');
  assert.equal(configuration.assets.directory, './dist-cloudflare');
  assert.deepEqual(configuration.assets.run_worker_first, ['/api/locale']);
  assert.equal(configuration.assets.not_found_handling, 'none');
});
