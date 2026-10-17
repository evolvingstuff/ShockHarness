import test from "node:test";
import assert from "node:assert/strict";
import { loadBoard } from "../src/load.js";
import { createNote } from "../src/notes.js";
import { writeNotes } from "../src/storage.js";
import { memoryStorage } from "./helpers.js";

const KEYS = { notes: "notes", quarantinePrefix: "bad." };

test("readable notes load without a problem", () => {
  const storage = memoryStorage({});
  writeNotes(storage, "notes", [createNote("a", "x", 1)]);
  const result = loadBoard(storage, KEYS, 42);
  assert.equal(result.problem, null);
  assert.equal(result.notes.length, 1);
});

test("unreadable data is quarantined, reported, and the board starts empty", () => {
  const storage = memoryStorage({ notes: "garbage" });
  const result = loadBoard(storage, KEYS, 42);
  assert.deepEqual(result.notes, []);
  assert.match(result.problem, /could not be read/);
  assert.match(result.problem, /bad\.42/);
  assert.equal(storage.map.get("bad.42"), "garbage");
  assert.equal(storage.map.has("notes"), false);
});

test("the problem is reported once: the next load is clean", () => {
  const storage = memoryStorage({ notes: "garbage" });
  loadBoard(storage, KEYS, 42);
  const second = loadBoard(storage, KEYS, 43);
  assert.equal(second.problem, null);
  assert.equal(storage.map.get("bad.42"), "garbage");
});

test("storage failures other than unreadable data propagate", () => {
  const storage = {
    getItem: () => {
      throw new TypeError("storage unavailable");
    },
  };
  assert.throws(() => loadBoard(storage, KEYS, 1), TypeError);
});
