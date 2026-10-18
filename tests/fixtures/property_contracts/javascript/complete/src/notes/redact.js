// src/notes/redact.js
import { requires, produces } from "../vendor/shockharness-contracts.js";

export function redact(note) {
  requires(note, "decrypted");
  return produces(stripPrivate(note), "redacted");
}

export function sendToModel(note) {
  requires(note, "redacted");
  return post(note);
}

export function summarize(note) {
  return sendToModel(redact(note));
}
