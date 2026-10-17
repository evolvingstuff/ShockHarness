// Board settings come from data attributes in index.html, not from source.

export function parseToastDuration(raw) {
  if (typeof raw !== "string" || raw.trim() === "") {
    throw new TypeError("data-toast-ms must be set to a duration in milliseconds");
  }
  const duration = Number(raw);
  if (!Number.isInteger(duration) || duration <= 0) {
    throw new RangeError(`data-toast-ms must be a positive integer, got ${JSON.stringify(raw)}`);
  }
  return duration;
}
