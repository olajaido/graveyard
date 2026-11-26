// Tests of the real headers template (EDGE-TEST-3). The same file serves the site and the API; only the header map differs.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const url = new URL('./viewer-response.js.tftpl', import.meta.url);
const template = readFileSync(url, 'utf8');
function load(headers) {
  const code = template.replaceAll('${headers_json}', JSON.stringify(headers));
  assert.ok(!code.includes('${'), 'every placeholder is replaced');
  const context = vm.createContext({});
  vm.runInContext(code, context);
  return context.handler;
}
const csp = "default-src 'self'; script-src 'self' 'unsafe-inline'; connect-src 'self' https://api.lastrites.dev; frame-ancestors 'none'";
const site = {
  'strict-transport-security': 'max-age=63072000; includeSubDomains',
  'content-security-policy': csp,
  'x-content-type-options': 'nosniff',
  'referrer-policy': 'strict-origin-when-cross-origin',
};
const api = { 'strict-transport-security': 'max-age=63072000; includeSubDomains', 'x-content-type-options': 'nosniff' };
function event(headers = {}) {
  return { request: { method: 'GET', uri: '/' }, response: { statusCode: 200, statusDescription: 'OK', headers, cookies: {} } };
}
test('every configured header is set, with the exact value', () => {
  const out = load(site)(event({ 'content-type': { value: 'text/html' } }));
  for (const [name, value] of Object.entries(site)) assert.equal(out.headers[name].value, value);
});
test('a value sent by the origin is replaced', () => {
  const out = load(site)(event({ 'content-security-policy': { value: "default-src *" }, 'x-content-type-options': { value: 'sniff' } }));
  assert.equal(out.headers['content-security-policy'].value, csp);
  assert.equal(out.headers['x-content-type-options'].value, 'nosniff');
});
test('other headers, the status and the cookies are left alone', () => {
  const out = load(site)(event({ 'content-type': { value: 'text/html' }, 'cache-control': { value: 'no-cache' } }));
  assert.deepEqual(out.headers['content-type'], { value: 'text/html' });
  assert.deepEqual(out.headers['cache-control'], { value: 'no-cache' });
  assert.equal(out.statusCode, 200);
  assert.deepEqual(out.cookies, {});
});
test('the API map sets only HSTS and nosniff', () => {
  const out = load(api)(event({ 'content-type': { value: 'application/problem+json' } }));
  assert.deepEqual(Object.keys(out.headers).sort(), ['content-type', 'strict-transport-security', 'x-content-type-options']);
});
test('header names are lower case, as CloudFront requires', () => {
  for (const name of [...Object.keys(site), ...Object.keys(api)]) assert.equal(name, name.toLowerCase());
});
test('the site and the API use the same template file', () => {
  const other = readFileSync(new URL('../../edge-api/functions/viewer-response.js.tftpl', import.meta.url), 'utf8');
  assert.equal(other, template);
});
