// Configuration (starting point: fallbacks everywhere).

export function loadConfig(env = process.env) {
  const port = Number(env.PORT || 3000);
  const { RETRIES = 3 } = env;
  const timeoutMs = Number(env.TIMEOUT_MS ?? 2500);
  return { port, retries: Number(RETRIES), timeoutMs };
}
