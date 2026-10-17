// Edit-mode decisions, kept free of the DOM. The UI describes an event in
// plain terms and gets back what to do.

// A pointer press while editing.
//   editingId: id of the note being edited, or null
//   pressedNoteId: id of the note the press landed in, or null
//   inOverlay: the press landed in a modal or toast (not part of the board)
// Returns 'none' | 'commit' | 'enter'.
export function onPress({ editingId, pressedNoteId, inOverlay, onToolbar = false }) {
  if (inOverlay) return 'none';
  if (editingId !== null) {
    if (pressedNoteId === editingId) return 'none';
    return 'commit';
  }
  if (pressedNoteId !== null && !onToolbar) return 'enter';
  return 'none';
}

// A key press. Returns 'none' | 'cancel' | 'close-modal'.
export function onKey({ key, editingId, modalOpen }) {
  if (key !== 'Escape') return 'none';
  if (modalOpen) return 'close-modal';
  if (editingId !== null) return 'cancel';
  return 'none';
}
