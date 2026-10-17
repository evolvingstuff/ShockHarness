import { test } from "node:test";
import assert from "node:assert/strict";

import { InvalidNotesError, LOAD_CORRUPT, LOAD_OK, loadNotes, quarantineCorrupt, saveNotes } from "../src/storage.js";
import { createNote } from "../src/notes.js";

// A Storage-like object backed by a Map, standing in for localStorage.
function memoryStorage(entries) {
  const data = new Map(entries);
  return {
    getItem: (key) => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => {
      data.set(key, String(value));
    },
    removeItem: (key) => {
      data.delete(key);
    },
  };
}

const KEY = "notes";
const BACKUP = "notes.unreadable";

test("nothing stored loads an empty list", () => {
  const loaded = loadNotes(memoryStorage([]), KEY);
  assert.equal(loaded.status, LOAD_OK);
  assert.deepEqual(loaded.notes, []);
});

test("saved notes load back unchanged", () => {
  const storage = memoryStorage([]);
  const notes = [createNote("a", "first"), { ...createNote("b", "second"), pinned: true }];
  saveNotes(storage, KEY, notes);
  const loaded = loadNotes(storage, KEY);
  assert.equal(loaded.status, LOAD_OK);
  assert.deepEqual(loaded.notes, notes);
});

test("text that is not JSON is reported as corrupt with its raw text", () => {
  const loaded = loadNotes(memoryStorage([[KEY, "{not json"]]), KEY);
  assert.equal(loaded.status, LOAD_CORRUPT);
  assert.equal(loaded.raw, "{not json");
  assert.match(loaded.reason, /not valid JSON/);
});

for (const [label, raw] of [
  ["an object instead of a list", '{"id":"a"}'],
  ["an entry without text", '[{"id":"a","pinned":false}]'],
  ["an entry without an id", '[{"text":"x","pinned":false}]'],
  ["an entry without a pinned flag", '[{"id":"a","text":"x"}]'],
  ["a null entry", "[null]"],
  ["duplicate ids", '[{"id":"a","text":"x","pinned":false},{"id":"a","text":"y","pinned":true}]'],
]) {
  test(`${label} is reported as corrupt`, () => {
    const loaded = loadNotes(memoryStorage([[KEY, raw]]), KEY);
    assert.equal(loaded.status, LOAD_CORRUPT);
    assert.equal(loaded.raw, raw);
  });
}

test("quarantining keeps the unreadable data and leaves an empty readable list", () => {
  const storage = memoryStorage([[KEY, "garbage"]]);
  quarantineCorrupt(storage, KEY, BACKUP, "garbage");
  assert.equal(storage.getItem(BACKUP), "garbage");
  const loaded = loadNotes(storage, KEY);
  assert.equal(loaded.status, LOAD_OK);
  assert.deepEqual(loaded.notes, []);
});

test("saving an invalid list is refused", () => {
  assert.throws(() => saveNotes(memoryStorage([]), KEY, [{ id: "a" }]), InvalidNotesError);
});

test("a storage failure other than bad JSON propagates", () => {
  const broken = { getItem: () => { throw new TypeError("storage is unavailable"); } };
  assert.throws(() => loadNotes(broken, KEY), TypeError);
});
