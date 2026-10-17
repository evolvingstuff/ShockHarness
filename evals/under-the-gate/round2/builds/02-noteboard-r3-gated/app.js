import {
  CLICK_BEGIN_EDIT,
  KEY_CANCEL,
  NOT_EDITING,
  PRESS_SAVE,
  afterRemoval,
  beginEditing,
  decideKey,
  decideNoteClick,
  decidePress,
  withDraft,
} from "./src/editMode.js";
import { addNote, createNote, displayOrder, findNote, removeNote, togglePin, updateText } from "./src/notes.js";
import { LOAD_UNREADABLE, loadNotes, saveNotes } from "./src/storage.js";
import { parseToastMs } from "./src/settings.js";
import { ACTION_DELETE, ACTION_PIN, editorOf, renderList, rerenderNote } from "./src/dom/render.js";
import { TOAST_STICKY, TOAST_TRANSIENT, createToaster } from "./src/dom/toast.js";
import { isDialogOpen, openConfirm } from "./src/dom/modal.js";

/**
 * Starts the board. `options` holds: document, storage (a Storage), newId() returning a
 * fresh note id, and now() returning the current time in milliseconds.
 */
export function start(options) {
  const doc = options.document;
  const storage = options.storage;
  const toastMs = parseToastMs(doc.body.dataset.toastMs);
  const list = doc.getElementById("notes");
  const addButton = doc.getElementById("add-note");
  if (list === null || addButton === null) {
    throw new Error("the page needs #notes and #add-note");
  }
  const toaster = createToaster(doc, toastMs);

  const loaded = loadNotes(storage, options.now());
  let notes = loaded.notes;
  let editing = NOT_EDITING;
  if (loaded.status === LOAD_UNREADABLE) {
    toaster.show(loaded.message, TOAST_STICKY);
  }

  function render() {
    renderList(doc, list, displayOrder(notes), editing);
    if (editing.active) {
      const area = editorOf(list);
      area.focus();
      area.setSelectionRange(area.value.length, area.value.length);
    }
  }

  function commit(nextNotes) {
    saveNotes(storage, nextNotes);
    notes = nextNotes;
  }

  function leaveEditing(nextNotes) {
    const id = editing.id;
    editing = NOT_EDITING;
    rerenderNote(doc, list, findNote(nextNotes, id), editing);
  }

  function saveEditing() {
    const nextNotes = updateText(notes, editing.id, editing.draft);
    commit(nextNotes);
    leaveEditing(nextNotes);
    toaster.show("Saved", TOAST_TRANSIENT);
  }

  function confirmDelete(id) {
    openConfirm(doc, {
      message: "Delete this note?",
      confirmLabel: "Delete",
      onConfirm: () => {
        commit(removeNote(notes, id));
        editing = afterRemoval(editing, id);
        render();
      },
    });
  }

  function runAction(action, id) {
    if (action === ACTION_PIN) {
      commit(togglePin(notes, id));
      render();
    } else if (action === ACTION_DELETE) {
      confirmDelete(id);
    } else {
      throw new RangeError(`unknown note action ${action}`);
    }
  }

  // A press outside the note being edited saves it. Only that note is re-rendered, so the
  // element under the pointer survives and its click still arrives.
  doc.addEventListener(
    "pointerdown",
    (event) => {
      const target = event.target instanceof Element ? event.target : doc.body;
      const item = target.closest("li[data-id]");
      const press = {
        noteId: item === null ? null : item.dataset.id,
        inDialog: target.closest("dialog") !== null,
      };
      if (decidePress(editing, press) === PRESS_SAVE) {
        saveEditing();
      }
    },
    { capture: true },
  );

  doc.addEventListener("keydown", (event) => {
    if (decideKey(editing, { key: event.key, dialogOpen: isDialogOpen(doc) }) === KEY_CANCEL) {
      event.preventDefault();
      leaveEditing(notes);
    }
  });

  list.addEventListener("input", (event) => {
    if (editing.active && event.target instanceof Element && event.target.matches("textarea.editor")) {
      editing = withDraft(editing, event.target.value);
    }
  });

  // One delegated listener for the toolbar buttons and for entering edit mode.
  list.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) {
      return;
    }
    const item = event.target.closest("li[data-id]");
    if (item === null) {
      return;
    }
    const id = item.dataset.id;
    const button = event.target.closest("button[data-action]");
    if (button !== null) {
      runAction(button.dataset.action, id);
      return;
    }
    if (decideNoteClick(editing, id) === CLICK_BEGIN_EDIT) {
      editing = beginEditing(findNote(notes, id));
      render();
    }
  });

  addButton.addEventListener("click", () => {
    const note = createNote(options.newId(), "");
    commit(addNote(notes, note));
    editing = beginEditing(note);
    render();
  });

  render();
}
