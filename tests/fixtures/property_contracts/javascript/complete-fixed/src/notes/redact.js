// src/notes/redact.js, after the property-contracts skill's procedure
import { preserves, produces, requires } from "../vendor/shockharness-contracts.js";

export function redact(note) {
  requires(note, "decrypted");
  return produces(stripPrivate(note), "redacted");
}

export function sendToModel(note) {
  requires(note, "redacted");
  post(note);
}

export function summarize(note) {
  requires(note, "decrypted");
  const redacted = redact(note);
  sendToModel(redacted);
  return preserves(redacted, redacted);
}
