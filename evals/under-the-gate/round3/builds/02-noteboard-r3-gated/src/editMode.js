// Edit-mode decisions, kept free of the DOM. The DOM layer describes what was
// pressed or clicked; these functions say what the board does about it.

export const NOT_EDITING = null;

export const PRESS = Object.freeze({
  IGNORE: "ignore",
  // Save the note being edited and leave edit mode.
  SAVE: "save",
});

export const KEY = Object.freeze({
  IGNORE: "ignore",
  CLOSE_MODAL: "close-modal",
  // Leave edit mode without saving.
  CANCEL_EDIT: "cancel-edit",
});

export const LIST_CLICK = Object.freeze({
  NONE: "none",
  EDIT: "edit",
  PIN: "pin",
  DELETE: "delete",
});

const TOOLBAR_ACTIONS = Object.freeze({
  pin: LIST_CLICK.PIN,
  delete: LIST_CLICK.DELETE,
});

/**
 * A press (pointerdown) anywhere on the page.
 * `pressedNoteId` is the note the press landed in, or null.
 * `onOverlay` is true for presses in the modal or a toast: they sit above the
 * board and do not count as "outside the note", so their buttons work whether
 * or not a note is being edited.
 */
export function decidePress({ editingId, pressedNoteId, onOverlay }) {
  if (editingId === NOT_EDITING || onOverlay) {
    return PRESS.IGNORE;
  }
  if (pressedNoteId === editingId) {
    return PRESS.IGNORE;
  }
  return PRESS.SAVE;
}

export function decideKey({ key, editingId, modalOpen }) {
  if (key !== "Escape") {
    return KEY.IGNORE;
  }
  if (modalOpen) {
    return KEY.CLOSE_MODAL;
  }
  if (editingId === NOT_EDITING) {
    return KEY.IGNORE;
  }
  return KEY.CANCEL_EDIT;
}

/**
 * A click inside the list. `action` is the data-action of the toolbar button
 * clicked, or null when the click was not on a button.
 */
export function decideListClick({ noteId, action, editingId }) {
  if (noteId === null) {
    return LIST_CLICK.NONE;
  }
  if (action !== null) {
    if (!Object.hasOwn(TOOLBAR_ACTIONS, action)) {
      throw new Error(`unknown toolbar action ${JSON.stringify(action)}`);
    }
    return TOOLBAR_ACTIONS[action];
  }
  if (noteId === editingId) {
    return LIST_CLICK.NONE;
  }
  return LIST_CLICK.EDIT;
}
