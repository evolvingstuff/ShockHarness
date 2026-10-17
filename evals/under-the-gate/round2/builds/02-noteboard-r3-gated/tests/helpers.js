// A Storage stand-in for tests: getItem, setItem, removeItem over a Map.

export function memoryStorage(entries) {
  const items = new Map(entries);
  return Object.freeze({
    getItem: (key) => (items.has(key) ? items.get(key) : null),
    setItem: (key, value) => {
      items.set(key, String(value));
    },
    removeItem: (key) => {
      items.delete(key);
    },
    keys: () => [...items.keys()],
  });
}
