// HTTP status handling: protocol constants named once, each citing its source.
// The findings stay in every report with the suppression attached; only the gate ignores them.

export const OK = 200; // shockharness: ignore[MAGIC001] reason="RFC 9110 section 15.3.1"
export const NOT_FOUND = 404; // shockharness: ignore[MAGIC001] reason="RFC 9110 section 15.5.5"
export const SERVER_ERROR_FLOOR = 500; // shockharness: ignore[MAGIC001] reason="RFC 9110 section 15.6: 5xx server error class"

export function isOk(status) {
  return status === OK;
}

export function isMissing(status) {
  return status === NOT_FOUND;
}

export function isServerError(status) {
  return status >= SERVER_ERROR_FLOOR;
}
