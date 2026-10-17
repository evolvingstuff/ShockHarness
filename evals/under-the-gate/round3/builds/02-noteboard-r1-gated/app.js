import { startBoard } from "./src/board.js";

const STORAGE_KEY = "noteboard.notes";

function readToastMs(body) {
  const raw = body.dataset.toastMs;
  const toastMs = Number(raw);
  if (!Number.isInteger(toastMs) || toastMs <= 0) {
    throw new TypeError(`data-toast-ms on <body> must be a positive integer, got ${raw}`);
  }
  return toastMs;
}

function requireElement(id) {
  const element = document.getElementById(id);
  if (element === null) {
    throw new Error(`the page has no element with id "${id}"`);
  }
  return element;
}

startBoard({
  list: requireElement("notes"),
  addButton: requireElement("add-note"),
  storage: window.localStorage,
  storageKey: STORAGE_KEY,
  toastMs: readToastMs(document.body),
  newId: () => crypto.randomUUID(),
});
