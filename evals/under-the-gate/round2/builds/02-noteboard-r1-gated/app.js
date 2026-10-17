// Wires the board to the page. `start` is called from index.html.

import { parseToastDuration } from "./src/config.js";
import {
  ACTION_CANCEL,
  ACTION_SAVE,
  ACTION_START,
  PRESS_ELSEWHERE,
  PRESS_IN_EDITED_NOTE,
  PRESS_IN_OVERLAY,
  VIEWING,
  afterDelete,
  decideKey,
  decideNoteClick,
  decidePress,
  editing,
  MODE_EDITING,
} from "./src/editMode.js";
import { addNote, displayOrder, removeNote, togglePinned, updateText } from "./src/state.js";
import { READ_UNREADABLE, readStoredNotes, setAsideUnreadable, writeNotes } from "./src/storage.js";
import { ACTION_ATTRIBUTE, NOTE_ID_ATTRIBUTE, createBoardView } from "./src/dom/board.js";
import { isModalOpen, openConfirm } from "./src/dom/modal.js";
import { OVERLAY_ATTRIBUTE } from "./src/dom/overlay.js";
import { createToaster } from "./src/dom/toast.js";

function requireElement(doc, selector) {
  const element = doc.querySelector(selector);
  if (element === null) {
    throw new Error(`index.html has no ${selector}`);
  }
  return element;
}

function classifyPress(target, edit) {
  if (!(target instanceof Element)) {
    return PRESS_ELSEWHERE;
  }
  if (target.closest(`[${OVERLAY_ATTRIBUTE}]`) !== null) {
    return PRESS_IN_OVERLAY;
  }
  const note = target.closest(`[${NOTE_ID_ATTRIBUTE}]`);
  if (edit.mode === MODE_EDITING && note !== null && note.getAttribute(NOTE_ID_ATTRIBUTE) === edit.noteId) {
    return PRESS_IN_EDITED_NOTE;
  }
  return PRESS_ELSEWHERE;
}

function loadInitialNotes(storage, toaster) {
  const read = readStoredNotes(storage);
  if (read.status !== READ_UNREADABLE) {
    return read.notes;
  }
  const keptUnder = setAsideUnreadable(storage, read.raw, new Date().toISOString());
  toaster.showProblem(
    `Your stored notes could not be read (${read.reason}). ` +
      `They were kept in localStorage under "${keptUnder}" and the board starts empty.`,
  );
  return Object.freeze([]);
}

export function start(doc, storage) {
  const toaster = createToaster(
    doc,
    requireElement(doc, "#toasts"),
    parseToastDuration(doc.body.dataset.toastMs),
  );
  const list = requireElement(doc, "#notes");
  const view = createBoardView(list, requireElement(doc, "#empty"));
  let notes = loadInitialNotes(storage, toaster);
  let edit = VIEWING;

  function show() {
    view.render(displayOrder(notes), edit);
    if (edit.mode === MODE_EDITING && doc.activeElement !== view.elementFor(edit.noteId).querySelector("textarea")) {
      view.focusEditor(edit.noteId);
    }
  }

  function setNotes(next) {
    writeNotes(storage, next);
    notes = next;
  }

  function saveEdited() {
    setNotes(updateText(notes, edit.noteId, view.draftText(edit.noteId)));
    edit = VIEWING;
    show();
    toaster.showBrief("Saved");
  }

  function startEditing(noteId) {
    edit = editing(noteId);
    show();
  }

  function confirmDelete(noteId) {
    openConfirm(doc, {
      message: "Delete this note?",
      confirmLabel: "Delete",
      onConfirm: () => {
        setNotes(removeNote(notes, noteId));
        edit = afterDelete(edit, noteId);
        show();
      },
      onCancel: () => show(),
    });
  }

  doc.addEventListener(
    "pointerdown",
    (event) => {
      if (decidePress(edit, classifyPress(event.target, edit)) === ACTION_SAVE) {
        saveEdited();
      }
    },
    { capture: true },
  );

  doc.addEventListener("keydown", (event) => {
    if (decideKey(edit, event.key, isModalOpen(doc)) === ACTION_CANCEL) {
      event.preventDefault();
      edit = VIEWING;
      show();
    }
  });

  list.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) {
      return;
    }
    const control = event.target.closest(`[${ACTION_ATTRIBUTE}]`);
    const note = event.target.closest(`[${NOTE_ID_ATTRIBUTE}]`);
    if (control === null || note === null || !list.contains(note)) {
      return;
    }
    const noteId = note.getAttribute(NOTE_ID_ATTRIBUTE);
    const action = control.getAttribute(ACTION_ATTRIBUTE);
    if (action === "pin") {
      setNotes(togglePinned(notes, noteId));
      show();
    } else if (action === "delete") {
      confirmDelete(noteId);
    } else if (action === "edit" && decideNoteClick(edit, noteId) === ACTION_START) {
      startEditing(noteId);
    }
  });

  requireElement(doc, "#new-note").addEventListener("click", () => {
    const noteId = crypto.randomUUID();
    setNotes(addNote(notes, noteId, ""));
    startEditing(noteId);
  });

  show();
}
