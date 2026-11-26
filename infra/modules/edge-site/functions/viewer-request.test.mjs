// Tests of the real viewer-request template (EDGE-TEST-3). The template is read from disk and its two placeholders are replaced by
// plain string substitution, so this test and the file Terraform renders cannot drift apart. Run: node --test infra/modules/edge-site/functions
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const template = readFileSync(new URL('./viewer-request.js.tftpl', import.meta.url), 'utf8');
function load(apexHost, redirectWww) {
  const code = template.replaceAll('${apex_host}', apexHost).replaceAll('${redirect_www}', String(redirectWww));
  assert.ok(!code.includes('${'), 'every placeholder is replaced');
  const context = vm.createContext({});
  vm.runInContext(code, context);
  return context.handler;
}
function event(uri, { host = 'lastrites.dev', querystring = {} } = {}) {
  return { request: { method: 'GET', uri, querystring, headers: { host: { value: host } }, cookies: {} } };
}
const prod = load('lastrites.dev', true);
const dev = load('dev.lastrites.dev', false);
test('clean URLs map to the html file', () => {
  assert.equal(prod(event('/')).uri, '/index.html');
  assert.equal(prod(event('/scan')).uri, '/scan.html');
  assert.equal(prod(event('/grave')).uri, '/grave.html');
  assert.equal(prod(event('/scan/')).uri, '/scan.html');
  assert.equal(prod(event('/nope')).uri, '/nope.html');
  assert.equal(prod(event('/a.b/c')).uri, '/a.b/c.html');
});
test('a path whose last segment has an extension is left alone', () => {
  for (const uri of ['/index.html', '/scan.html', '/_next/static/chunks/a1b2.js', '/scan.txt', '/__next.scan.txt', '/404.html', '/icon.svg', '/_next/static/media/f.woff2']) {
    assert.equal(prod(event(uri)).uri, uri);
  }
});
test('the request is returned, not a response, and the method and query string are untouched', () => {
  const e = event('/scan', { querystring: { id: { value: 'x' } } });
  const out = prod(e);
  assert.equal(out.method, 'GET');
  assert.deepEqual(out.querystring, { id: { value: 'x' } });
  assert.equal(out.statusCode, undefined);
});
test('prod: www redirects to the apex with 301, the path and the query string', () => {
  const out = prod(event('/scan', { host: 'www.lastrites.dev', querystring: { id: { value: 'a%20b' }, x: { value: '2' } } }));
  assert.equal(out.statusCode, 301);
  assert.equal(out.headers.location.value, 'https://lastrites.dev/scan?id=a%20b&x=2');
});
test('prod: www redirect keeps repeated parameters and a path without a query string', () => {
  const multi = prod(event('/grave', { host: 'www.lastrites.dev', querystring: { p: { value: '1', multiValue: [{ value: '1' }, { value: '2' }] } } }));
  assert.equal(multi.headers.location.value, 'https://lastrites.dev/grave?p=1&p=2');
  assert.equal(prod(event('/', { host: 'www.lastrites.dev' })).headers.location.value, 'https://lastrites.dev/');
});
test('prod: the host is compared in lower case and the apex does not redirect', () => {
  assert.equal(prod(event('/scan', { host: 'WWW.lastrites.dev' })).statusCode, 301);
  assert.equal(prod(event('/scan', { host: 'lastrites.dev' })).uri, '/scan.html');
});
test('dev never redirects, even for a www host', () => {
  assert.equal(dev(event('/scan', { host: 'www.dev.lastrites.dev' })).statusCode, undefined);
  assert.equal(dev(event('/scan', { host: 'dev.lastrites.dev' })).uri, '/scan.html');
});
