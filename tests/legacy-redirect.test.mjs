import test from 'node:test';
import assert from 'node:assert/strict';
import legacy from '../server/legacy-worker.mjs';

test('old entry points redirect to the chosen host with queries preserved', async () => {
  for (const pathname of ['/', '/index.html']) {
    for (const method of ['GET', 'HEAD']) {
      const response = await legacy.fetch(new Request(`https://film-lab.film-lab-jc.workers.dev${pathname}?from=cafe&look=C200%20STD`, { method }), {});
      assert.equal(response.status, 308);
      assert.equal(response.headers.get('Location'), `https://sosang.film-lab-jc.workers.dev${pathname}?from=cafe&look=C200%20STD`);
    }
  }
});

test('existing tabs can still fetch assets from their original origin', async () => {
  const request = new Request('https://film-lab.film-lab-jc.workers.dev/luts/c200/0001LUTS.zip');
  const response = await legacy.fetch(request, { ASSETS: { fetch: received => {
    assert.equal(received, request);
    return new Response('existing LUT bytes');
  } } });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('Location'), null);
  assert.equal(await response.text(), 'existing LUT bytes');
});

test('existing tabs retain country-based locale responses', async () => {
  const request = new Request('https://film-lab.film-lab-jc.workers.dev/api/locale');
  Object.defineProperty(request, 'cf', { value: { country: 'KR' } });
  const response = await legacy.fetch(request, {});
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { locale: 'ko' });
});
