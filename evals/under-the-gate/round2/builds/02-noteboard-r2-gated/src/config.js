// Validation of configuration read from the page (data-* attributes on <body>).

import { isNonEmptyString } from "./checks.js";

export class ConfigError extends Error {}

/** Parses a duration in milliseconds given as text; it must be a positive integer. */
export function parseDurationMs(name, text) {
  if (!isNonEmptyString(text)) {
    throw new ConfigError(`${name} is missing`);
  }
  const value = Number(text);
  if (!Number.isInteger(value) || value <= 0) {
    throw new ConfigError(`${name} must be a positive integer number of milliseconds, got ${text}`);
  }
  return value;
}

export function requireText(name, text) {
  if (!isNonEmptyString(text)) {
    throw new ConfigError(`${name} is missing`);
  }
  return text;
}
