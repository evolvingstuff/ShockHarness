// A Storage stand-in for tests: the subset of the Web Storage API the board uses.
export class MemoryStorage {
  constructor(entries) {
    this.map = new Map(Object.entries(entries));
  }
  getItem(key) {
    return this.map.has(key) ? this.map.get(key) : null;
  }
  setItem(key, value) {
    this.map.set(key, String(value));
  }
  removeItem(key) {
    this.map.delete(key);
  }
  keys() {
    return [...this.map.keys()];
  }
}
