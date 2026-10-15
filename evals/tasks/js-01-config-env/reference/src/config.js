// Configuration is explicit: every value is required and validated once, at load.

function requirePositiveInteger(env, name) {
  const value = Number(env[name]);
  if (!Number.isInteger(value) || value <= 0) {
    throw new TypeError(`${name} must be a positive integer, got ${env[name]}`);
  }
  return value;
}

function requireNonNegativeInteger(env, name) {
  const value = Number(env[name]);
  if (!Number.isInteger(value) || value < 0) {
    throw new TypeError(`${name} must be a non-negative integer, got ${env[name]}`);
  }
  return value;
}

function requirePositiveNumber(env, name) {
  const value = Number(env[name]);
  if (!Number.isFinite(value) || value <= 0) {
    throw new TypeError(`${name} must be a positive number, got ${env[name]}`);
  }
  return value;
}

export function loadConfig(env) {
  return Object.freeze({
    port: requirePositiveInteger(env, "PORT"),
    retries: requireNonNegativeInteger(env, "RETRIES"),
    timeoutMs: requirePositiveNumber(env, "TIMEOUT_MS"),
  });
}
