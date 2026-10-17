// Testable logic modules must not touch the DOM.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

for (const f of ['storage.js', 'state.js', 'editmode.js']) {
  test(`src/${f} does not reference document or window`, () => {
    const src = readFileSync(new URL(`../src/${f}`, import.meta.url), 'utf8');
    assert.doesNotMatch(src, /\b(document|window)\b/);
  });
}
