// Page configuration read from data attributes; validated here so a missing
// or malformed value fails at start-up.

import { isString } from "./checks.js";

export function parseToastDuration(text) {
  if (!isString(text) || !/^\d+$/.test(text)) {
    throw new TypeError(`data-toast-ms must be a whole number of milliseconds, got ${text}`);
  }
  const ms = Number(text);
  if (!Number.isSafeInteger(ms) || ms <= 0) {
    throw new RangeError(`data-toast-ms must be positive, got ${text}`);
  }
  return ms;
}
