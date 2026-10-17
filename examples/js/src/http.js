// One documented, suppressed literal: a protocol constant with an authoritative source.
// The MAGIC001 finding stays in every report with the suppression attached.
export const NOT_FOUND = 404; // RFC 9110 section 15.5.5

export function isMissing(status) {
  return status === NOT_FOUND;
}
