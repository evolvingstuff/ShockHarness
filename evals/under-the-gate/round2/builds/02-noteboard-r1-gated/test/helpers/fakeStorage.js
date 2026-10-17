// A Map-backed stand-in for the Web Storage interface used by src/storage.js.
export function createFakeStorage(entries) {
  const items = new Map(entries);
  return {
    getItem: (key) => (items.has(key) ? items.get(key) : null),
    setItem: (key, value) => items.set(key, String(value)),
    removeItem: (key) => items.delete(key),
    keys: () => [...items.keys()],
  };
}
