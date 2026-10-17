// Wires the notes board to the page: rendering, edit mode, toolbar actions,
// the delete confirmation and the toasts.

import {
  KEY,
  NOTE_CLICK,
  NOT_EDITING,
  PRESS,
  beginEdit,
  commitEdit,
  decideKey,
  decideNoteClick,
  decidePress,
  deleteNote,
  isEditing,
  withDraft,
} from "./edit-mode.js";
import { isFloatingControl } from "./floating.js";
import { confirmInModal } from "./modal.js";
import { addNote, createNote, findNote, orderedForDisplay, togglePin } from "./notes.js";
import { openNotes, saveNotes } from "./storage.js";
import { showToast } from "./toast.js";
import { ACTION, ACTION_SELECTOR, NOTE_SELECTOR, renderNote } from "./view.js";

const SAVED_MESSAGE = "Saved";

function noteIdAt(target) {
  if (!(target instanceof Element)) {
    return null;
  }
  const item = target.closest(NOTE_SELECTOR);
  if (item === null) {
    return null;
  }
  return item.dataset.noteId;
}

/**
 * settings: { list, addButton, storage, storageKey, toastMs, newId }.
 * Starts the board in the document that owns settings.list.
 */
export function startBoard(settings) {
  const { list, addButton, storage, storageKey, toastMs, newId } = settings;
  const doc = list.ownerDocument;
  const opened = openNotes(storage, storageKey, new Date());
  let notes = opened.notes;
  let session = NOT_EDITING;

  function render() {
    list.replaceChildren(...orderedForDisplay(notes).map((note) => renderNote(doc, note, session)));
    focusEditor();
  }

  function renderOne(id) {
    const current = list.querySelector(`[data-note-id="${CSS.escape(id)}"]`);
    current.replaceWith(renderNote(doc, findNote(notes, id), session));
  }

  function focusEditor() {
    const editor = list.querySelector(".note-editor");
    if (editor !== null) {
      editor.focus();
    }
  }

  function persist() {
    saveNotes(storage, storageKey, notes);
  }

  function saveEditing() {
    const id = session.editingId;
    const committed = commitEdit(notes, session);
    notes = committed.notes;
    session = committed.session;
    persist();
    renderOne(id);
    showToast(doc, SAVED_MESSAGE, toastMs);
  }

  function cancelEditing() {
    const id = session.editingId;
    session = NOT_EDITING;
    renderOne(id);
  }

  function askToDelete(id) {
    confirmInModal(doc, {
      message: "Delete this note? This cannot be undone.",
      confirmLabel: "Delete",
      onConfirm: () => {
        const result = deleteNote(notes, session, id);
        notes = result.notes;
        session = result.session;
        persist();
        render();
      },
    });
  }

  function runAction(action, id) {
    if (action === ACTION.PIN) {
      notes = togglePin(notes, id);
      persist();
      render();
      return;
    }
    if (action === ACTION.DELETE) {
      askToDelete(id);
      return;
    }
    throw new Error(`unknown note action ${JSON.stringify(action)}`);
  }

  list.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    const id = noteIdAt(target);
    if (id === null) {
      return;
    }
    const button = target.closest(ACTION_SELECTOR);
    if (button !== null) {
      runAction(button.dataset.action, id);
      return;
    }
    if (decideNoteClick(session, id) === NOTE_CLICK.BEGIN) {
      session = beginEdit(notes, id);
      render();
    }
  });

  list.addEventListener("input", (event) => {
    if (isEditing(session) && event.target.matches(".note-editor")) {
      session = withDraft(session, event.target.value);
    }
  });

  // Capture phase, and the edited note is re-rendered in place, so the press
  // that ends edit mode still reaches the control it landed on.
  doc.addEventListener(
    "pointerdown",
    (event) => {
      const press = {
        noteId: noteIdAt(event.target),
        onFloatingControl: isFloatingControl(event.target),
      };
      if (decidePress(session, press) === PRESS.SAVE) {
        saveEditing();
      }
    },
    { capture: true },
  );

  doc.addEventListener("keydown", (event) => {
    if (decideKey(session, event.key) === KEY.CANCEL) {
      cancelEditing();
    }
  });

  addButton.addEventListener("click", () => {
    const note = createNote(newId(), "");
    notes = addNote(notes, note);
    session = beginEdit(notes, note.id);
    persist();
    render();
  });

  render();
  if (opened.problem !== null) {
    showToast(doc, opened.problem, toastMs);
  }
}
