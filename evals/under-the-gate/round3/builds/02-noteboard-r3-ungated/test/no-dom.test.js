// The logic modules must stay usable without a DOM.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

for (const file of ['storage.js', 'state.js', 'editMode.js']) {
  test(`src/${file} does not touch the DOM`, async () => {
    const src = await readFile(new URL(`../src/${file}`, import.meta.url), 'utf8');
    const code = src.replace(/\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '');
    assert.doesNotMatch(code, /\b(document|window|localStorage)\b/);
  });
}
