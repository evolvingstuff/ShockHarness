// Response bodies (starting point: every failure becomes a value).

export function parseBody(text) {
  try {
    const data = JSON.parse(text);
    if (typeof data !== "object" || data === null) {
      return null;
    }
    return data;
  } catch (err) {
    return null;
  }
}

export function loadAll(loaders) {
  return Promise.all(loaders.map((load) => load().catch(() => [])));
}
