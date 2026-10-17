import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';

const root = new URL('../', import.meta.url);

test('testable modules do not touch the DOM', () => {
  for (const f of ['src/storage.js', 'src/state.js', 'src/editMode.js']) {
    const src = readFileSync(new URL(f, root), 'utf8');
    assert.doesNotMatch(src, /\b(document|window)\b/, f);
  }
});

test('no dependencies', () => {
  assert.equal(existsSync(new URL('node_modules', root)), false);
  const pkg = new URL('package.json', root);
  if (existsSync(pkg)) {
    const json = JSON.parse(readFileSync(pkg, 'utf8'));
    assert.deepEqual(Object.keys({ ...json.dependencies, ...json.devDependencies }), []);
  }
});
