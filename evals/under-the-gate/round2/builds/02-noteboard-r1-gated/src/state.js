// Pure operations on the list of notes. Every function returns a new frozen
// list; the input is never changed.

function freezeNote(note) {
  return Object.freeze({ id: note.id, text: note.text, pinned: note.pinned });
}

function indexOfId(notes, id) {
  const index = notes.findIndex((note) => note.id === id);
  if (index === -1) {
    throw new RangeError(`no note with id ${id}`);
  }
  return index;
}

function replaceAt(notes, index, note) {
  return Object.freeze(notes.map((existing, i) => (i === index ? freezeNote(note) : existing)));
}

export function findNote(notes, id) {
  return notes[indexOfId(notes, id)];
}

export function addNote(notes, id, text) {
  if (notes.some((note) => note.id === id)) {
    throw new RangeError(`a note with id ${id} already exists`);
  }
  return Object.freeze([freezeNote({ id, text, pinned: false }), ...notes]);
}

export function updateText(notes, id, text) {
  const index = indexOfId(notes, id);
  return replaceAt(notes, index, { ...notes[index], text });
}

export function togglePinned(notes, id) {
  const index = indexOfId(notes, id);
  return replaceAt(notes, index, { ...notes[index], pinned: !notes[index].pinned });
}

export function removeNote(notes, id) {
  const index = indexOfId(notes, id);
  return Object.freeze(notes.filter((_, i) => i !== index));
}

/** Pinned notes first; otherwise the stored order is kept. */
export function displayOrder(notes) {
  const ordered = [...notes.filter((note) => note.pinned), ...notes.filter((note) => !note.pinned)];
  if (ordered.length !== notes.length) {
    throw new Error("display order lost or duplicated notes");
  }
  return Object.freeze(ordered);
}
