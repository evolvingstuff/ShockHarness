// The notes board: wires storage, note state and edit mode to the page.
// Started from index.html with start(document, window).

import { parseDurationMs, requireText } from "./src/config.js";
import {
  ACTION_CANCEL,
  ACTION_SAVE,
  NOT_EDITING,
  isEditing,
  keyAction,
  pressAction,
  startEditing,
  withDraft,
} from "./src/editing.js";
import { addNote, createNote, deleteNote, displayOrder, togglePin, updateText } from "./src/notes.js";
import { LOAD_CORRUPT, loadNotes, quarantineCorrupt, saveNotes } from "./src/storage.js";
import { noteIdAt, renderBoard } from "./src/dom/board.js";
import { confirmDialog } from "./src/dom/modal.js";
import { isInOverlay } from "./src/dom/overlay.js";
import { DISMISS_AUTO, DISMISS_MANUAL, showToast } from "./src/dom/toast.js";

function readConfig(body) {
  return Object.freeze({
    storageKey: requireText("data-storage-key", body.dataset.storageKey),
    backupKey: requireText("data-backup-key", body.dataset.backupKey),
    toastDurationMs: parseDurationMs("data-toast-ms", body.dataset.toastMs),
  });
}

function initialNotes(doc, view, config) {
  const loaded = loadNotes(view.localStorage, config.storageKey);
  if (loaded.status !== LOAD_CORRUPT) {
    return loaded.notes;
  }
  quarantineCorrupt(view.localStorage, config.storageKey, config.backupKey, loaded.raw);
  showToast(
    doc,
    view,
    `Saved notes could not be read (${loaded.reason}). The board starts empty; ` +
      `the unreadable data was kept in localStorage under "${config.backupKey}".`,
    Object.freeze({ kind: DISMISS_MANUAL }),
  );
  return Object.freeze([]);
}

export function start(doc, view) {
  const config = readConfig(doc.body);
  const list = doc.getElementById("notes");
  const addButton = doc.getElementById("add-note");
  let notes = initialNotes(doc, view, config);
  let editing = NOT_EDITING;

  const render = () => renderBoard(doc, list, displayOrder(notes), editing);
  const persist = () => saveNotes(view.localStorage, config.storageKey, notes);

  const saveEdit = () => {
    notes = updateText(notes, editing.noteId, editing.draft);
    editing = NOT_EDITING;
    persist();
    render();
    showToast(doc, view, "Saved", Object.freeze({ kind: DISMISS_AUTO, durationMs: config.toastDurationMs }));
  };
  const cancelEdit = () => {
    editing = NOT_EDITING;
    render();
  };
  const beginEdit = (id) => {
    const note = notes.find((candidate) => candidate.id === id);
    editing = startEditing(id, note.text);
    render();
  };

  doc.addEventListener(
    "pointerdown",
    (event) => {
      if (!(event.target instanceof Element)) {
        return;
      }
      if (pressAction(editing, noteIdAt(event.target), isInOverlay(event.target)) === ACTION_SAVE) {
        saveEdit();
      }
    },
    Object.freeze({ capture: true }),
  );

  doc.addEventListener("keydown", (event) => {
    if (keyAction(editing, event.key) === ACTION_CANCEL) {
      cancelEdit();
    }
  });

  list.addEventListener("input", (event) => {
    if (isEditing(editing) && event.target.classList.contains("note-editor")) {
      editing = withDraft(editing, event.target.value);
    }
  });

  // One delegated listener for the toolbar buttons and for entering edit mode.
  list.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) {
      return;
    }
    const id = noteIdAt(event.target);
    if (id === null) {
      return;
    }
    const button = event.target.closest("button[data-action]");
    if (button === null) {
      if (editing.noteId !== id) {
        beginEdit(id);
      }
      return;
    }
    if (button.dataset.action === "pin") {
      notes = togglePin(notes, id);
      persist();
      render();
    } else if (button.dataset.action === "delete") {
      confirmDialog(doc, "Delete this note?", "Delete", () => {
        if (editing.noteId === id) {
          editing = NOT_EDITING;
        }
        notes = deleteNote(notes, id);
        persist();
        render();
      });
    } else {
      throw new RangeError(`unknown note action ${button.dataset.action}`);
    }
  });

  addButton.addEventListener("click", () => {
    const note = createNote(view.crypto.randomUUID(), "");
    notes = addNote(notes, note);
    persist();
    editing = startEditing(note.id, note.text);
    render();
  });

  render();
}
