export function createStore(initial = []) {
  let notes = initial.map((n) => ({ ...n }));
  let nextId = Date.now();
  const genId = () => {
    let id;
    do { id = 'n' + nextId++; } while (notes.some((n) => n.id === id));
    return id;
  };
  return {
    get notes() { return notes; },
    add(text = '') {
      const note = { id: genId(), text, pinned: false };
      notes = [...notes, note];
      return note;
    },
    update(id, text) {
      notes = notes.map((n) => (n.id === id ? { ...n, text } : n));
    },
    togglePin(id) {
      notes = notes.map((n) => (n.id === id ? { ...n, pinned: !n.pinned } : n));
    },
    remove(id) {
      notes = notes.filter((n) => n.id !== id);
    },
    // pinned first, otherwise stable order
    sorted() {
      return [...notes.filter((n) => n.pinned), ...notes.filter((n) => !n.pinned)];
    },
  };
}
