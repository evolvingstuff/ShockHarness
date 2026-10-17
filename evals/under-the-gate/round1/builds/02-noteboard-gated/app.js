import { NOT_EDITING, NO_NOTE, beginEdit, cancelEdit, pressOutside } from "./src/edit.js";
import { addNote, findNote, removeNote, togglePin, updateText } from "./src/notes.js";
import { loadNotes, saveNotes } from "./src/storage.js";
import { confirmDialog } from "./src/ui/modal.js";
import { renderList } from "./src/ui/render.js";
import { showToast } from "./src/ui/toast.js";

function readToastMs(doc) {
  const ms = Number(doc.body.dataset.toastMs);
  if (!Number.isInteger(ms) || ms <= 0) {
    throw new TypeError(`body[data-toast-ms] must be a positive integer, got ${doc.body.dataset.toastMs}`);
  }
  return ms;
}

export function start(doc, storage) {
  const toastMs = readToastMs(doc);
  const listEl = doc.getElementById("notes");
  const loaded = loadNotes(storage);
  const store = { notes: loaded.notes, editing: NOT_EDITING, draft: "" };

  const render = () => renderList(doc, listEl, store.notes, store.editing, store.draft);
  const persist = () => saveNotes(storage, store.notes);

  const commitSave = (id) => {
    store.notes = updateText(store.notes, id, store.draft);
    persist();
    showToast(doc, "Saved", toastMs);
  };

  const apply = (next) => {
    const previous = store.editing;
    if (next.saveId !== NOT_EDITING) commitSave(next.saveId);
    store.editing = next.editingId;
    if (next.editingId !== previous) {
      store.draft = next.editingId === NOT_EDITING ? "" : findNote(store.notes, next.editingId).text;
    }
    render();
    if (next.editingId !== NOT_EDITING && next.editingId !== previous) {
      listEl.querySelector("textarea").focus();
    }
  };

  const deleteNote = (id) => {
    store.notes = removeNote(store.notes, id);
    if (store.editing === id) {
      store.editing = NOT_EDITING;
      store.draft = "";
    }
    persist();
    render();
  };

  const act = (action, id) => {
    if (action === "pin") {
      store.notes = togglePin(store.notes, id);
      persist();
      render();
      return;
    }
    if (action === "delete") {
      confirmDialog(doc, "Delete this note?", () => deleteNote(id));
      return;
    }
    throw new RangeError(`unknown note action ${action}`);
  };

  listEl.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) return;
    const noteEl = event.target.closest("[data-note-id]");
    if (noteEl === null) return;
    const id = Number(noteEl.dataset.noteId);
    const button = event.target.closest("button[data-action]");
    if (button !== null) {
      act(button.dataset.action, id);
      return;
    }
    apply(beginEdit(store.editing, id));
  });

  listEl.addEventListener("input", (event) => {
    if (event.target instanceof HTMLTextAreaElement) store.draft = event.target.value;
  });

  doc.getElementById("new-note").addEventListener("click", (event) => {
    event.stopPropagation();
    store.notes = addNote(store.notes, "");
    const created = store.notes[store.notes.length - 1];
    persist();
    apply(beginEdit(store.editing, created.id));
  });

  doc.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) return;
    if (event.target.closest("[data-modal], [data-toast]") !== null) return;
    const noteEl = event.target.closest("[data-note-id]");
    let pressed = NO_NOTE;
    if (noteEl !== null) pressed = Number(noteEl.dataset.noteId);
    const next = pressOutside(store.editing, pressed);
    if (next.saveId !== NOT_EDITING) apply(next);
  });

  doc.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && store.editing !== NOT_EDITING) apply(cancelEdit());
  });

  render();
  if (loaded.problem !== null) {
    showToast(doc, `Saved notes could not be read (${loaded.problem}); starting empty. The old data is kept under its backup key.`, toastMs);
  }
}
