import { test } from "node:test";
import assert from "node:assert/strict";
import {
  STORAGE_KEY, UNREADABLE_KEY, decodeNotes, encodeNotes, loadNotes, saveNotes,
} from "../src/storage.js";
import { createNote, togglePin } from "../src/notes.js";

// A Map-backed stand-in for localStorage.
function fakeStorage(entries) {
  const data = new Map(Object.entries(entries));
  return {
    data,
    getItem: (key) => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => data.set(key, String(value)),
    removeItem: (key) => data.delete(key),
  };
}

test("no stored data starts an empty board without a problem", () => {
  const loaded = loadNotes(fakeStorage({}));
  assert.deepEqual(loaded.notes, []);
  assert.equal(loaded.problem, null);
});

test("saved notes load back", () => {
  const storage = fakeStorage({});
  const notes = togglePin([createNote("a", "hello"), createNote("b", "world")], "b");
  saveNotes(storage, notes);
  const loaded = loadNotes(storage);
  assert.equal(loaded.problem, null);
  assert.deepEqual(loaded.notes, notes);
});

for (const [name, raw] of [
  ["invalid JSON", "{not json"],
  ["a non-object", "[1,2]"],
  ["a wrong version", JSON.stringify({ version: 99, notes: [] })],
  ["missing notes", JSON.stringify({ version: 1 })],
  ["a malformed note", JSON.stringify({ version: 1, notes: [{ id: "a", text: 5, pinned: false }] })],
  ["duplicate ids", JSON.stringify({ version: 1, notes: [
    { id: "a", text: "", pinned: false }, { id: "a", text: "", pinned: true }] })],
]) {
  test(`${name} is reported, kept, and the board starts empty`, () => {
    const storage = fakeStorage({ [STORAGE_KEY]: raw });
    const loaded = loadNotes(storage);
    assert.deepEqual(loaded.notes, []);
    assert.equal(typeof loaded.problem, "string");
    assert.match(loaded.problem, /could not be read/);
    assert.equal(storage.data.get(UNREADABLE_KEY), raw);
    assert.equal(storage.data.has(STORAGE_KEY), false);
  });
}

test("unreadable data is reported once", () => {
  const storage = fakeStorage({ [STORAGE_KEY]: "garbage" });
  assert.notEqual(loadNotes(storage).problem, null);
  assert.equal(loadNotes(storage).problem, null);
  assert.equal(storage.data.get(UNREADABLE_KEY), "garbage");
});

test("decode returns an explicit failure for bad JSON", () => {
  const decoded = decodeNotes("{");
  assert.equal(decoded.ok, false);
  assert.match(decoded.reason, /not valid JSON/);
});

test("encode stores a versioned document", () => {
  const raw = encodeNotes([createNote("a", "t")]);
  assert.deepEqual(JSON.parse(raw), { version: 1, notes: [{ id: "a", text: "t", pinned: false }] });
});
