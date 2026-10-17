/** Toast duration from configuration text (a data attribute); must be a positive integer of ms. */
export function parseToastDurationMs(text) {
  if (typeof text !== "string" || !/^\d+$/.test(text)) {
    throw new TypeError(`toast duration must be a whole number of milliseconds, got ${text}`);
  }
  const duration = Number(text);
  if (duration <= 0) {
    throw new RangeError(`toast duration must be positive, got ${duration}`);
  }
  return duration;
}
