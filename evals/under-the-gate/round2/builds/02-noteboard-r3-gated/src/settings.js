import { isString } from "./types.js";

// Board settings come from the page (data attributes on <body>) and are validated here.

export function parseToastMs(text) {
  const value = Number(text);
  if (!isString(text) || text.trim() === "" || !Number.isInteger(value) || value <= 0) {
    throw new TypeError(`data-toast-ms must be a positive integer of milliseconds, got ${String(text)}`);
  }
  return value;
}
