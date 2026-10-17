import { createBoardView } from "./src/board-view.js";
import { parseToastDurationMs } from "./src/config.js";
import { Action, NOT_EDITING, decideKey, decideNoteClick, decidePress } from "./src/edit-mode.js";
import { loadBoard } from "./src/load.js";
import { confirmModal } from "./src/modal.js";
import { addNote, createNote, displayOrder, removeNote, togglePin, updateText } from "./src/notes.js";
import { writeNotes } from "./src/storage.js";
import { createToaster } from "./src/toast.js";

const STORAGE_KEYS = Object.freeze({
  notes: "noteboard.notes",
  quarantinePrefix: "noteboard.unreadable.",
});

const OVERLAY_SELECTOR = ".modal, .toast-area";

function noteIdAt(target) {
  const note = target.closest(".note");
  if (note === null) {
    return null;
  }
  return note.dataset.noteId;
}

function startBoard(doc, storage) {
  const list = doc.getElementById("notes");
  const view = createBoardView(doc, list);
  const toaster = createToaster(
    doc,
    doc.getElementById("toasts"),
    parseToastDurationMs(doc.body.dataset.toastDurationMs),
  );

  const loaded = loadBoard(storage, STORAGE_KEYS, Date.now());
  let notes = loaded.notes;
  let editingId = NOT_EDITING;

  function render() {
    view.render(displayOrder(notes), editingId);
  }

  function commit(nextNotes) {
    writeNotes(storage, STORAGE_KEYS.notes, nextNotes);
    notes = nextNotes;
  }

  function enterEdit(id) {
    editingId = id;
    render();
    view.focusEditor(id);
  }

  function saveEdit() {
    commit(updateText(notes, editingId, view.draftText(editingId)));
    editingId = NOT_EDITING;
    render();
    toaster.show("Saved");
  }

  function cancelEdit() {
    editingId = NOT_EDITING;
    render();
  }

  function deleteNote(id) {
    commit(removeNote(notes, id));
    if (editingId === id) {
      editingId = NOT_EDITING;
    }
    render();
  }

  function askToDelete(id) {
    confirmModal(doc, "Delete this note?", "Delete", () => deleteNote(id));
  }

  doc.addEventListener("pointerdown", (event) => {
    if (!(event.target instanceof Element)) {
      return;
    }
    const press = {
      noteId: noteIdAt(event.target),
      inOverlay: event.target.closest(OVERLAY_SELECTOR) !== null,
    };
    if (decidePress(editingId, press) === Action.SAVE) {
      saveEdit();
    }
  });

  doc.addEventListener("keydown", (event) => {
    const inOverlay = event.target instanceof Element && event.target.closest(OVERLAY_SELECTOR) !== null;
    if (decideKey(editingId, { key: event.key, inOverlay }) === Action.CANCEL) {
      event.preventDefault();
      cancelEdit();
    }
  });

  list.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) {
      return;
    }
    const id = noteIdAt(event.target);
    if (id === null) {
      return;
    }
    const button = event.target.closest("button[data-action]");
    if (button !== null) {
      if (button.dataset.action === "pin") {
        commit(togglePin(notes, id));
        render();
      } else if (button.dataset.action === "delete") {
        askToDelete(id);
      }
      return;
    }
    if (decideNoteClick(editingId, id) === Action.ENTER) {
      enterEdit(id);
    }
  });

  doc.getElementById("add-note").addEventListener("click", () => {
    const note = createNote(crypto.randomUUID(), "", Date.now());
    commit(addNote(notes, note));
    enterEdit(note.id);
  });

  render();
  if (loaded.problem !== null) {
    toaster.show(loaded.problem);
  }
}

startBoard(document, window.localStorage);
