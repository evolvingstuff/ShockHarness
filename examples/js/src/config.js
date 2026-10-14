// Configuration is explicit: every value is required and validated once, at load.

export function loadConfig(env) {
  const raw = env.REQUEST_TIMEOUT_MS;
  const timeout = Number(raw);
  if (!Number.isFinite(timeout) || timeout <= 0) {
    throw new TypeError(`REQUEST_TIMEOUT_MS must be a positive number, got ${raw}`);
  }
  return Object.freeze({ requestTimeoutMs: timeout });
}
