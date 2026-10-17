// The board: renders the notes and wires the page events to the pure
// decisions in editMode.js and the pure operations in notes.js.

import {
  KEY, LIST_CLICK, NOT_EDITING, PRESS, decideKey, decideListClick, decidePress,
} from "./editMode.js";
import { actionOf, isOnOverlay, noteIdOf } from "./dom.js";
import { icon } from "./icons.js";
import { openConfirm } from "./modal.js";
import {
  addNote, createNote, displayOrder, findNote, removeNote, togglePin, updateText,
} from "./notes.js";
import { saveNotes } from "./storage.js";

const NO_MODAL = null;

function toolbarButton(doc, action, label) {
  const button = doc.createElement("button");
  button.type = "button";
  button.className = "icon-button";
  button.dataset.action = action;
  button.setAttribute("aria-label", label);
  button.title = label;
  button.append(icon(doc, action));
  return button;
}

function renderNote(doc, note, editing, draft) {
  const item = doc.createElement("li");
  item.className = "note";
  item.dataset.noteId = note.id;
  item.classList.toggle("pinned", note.pinned);
  item.classList.toggle("editing", editing);

  if (editing) {
    const area = doc.createElement("textarea");
    area.className = "note-editor";
    area.value = draft;
    area.setAttribute("aria-label", "Note text");
    item.append(area);
  } else {
    const text = doc.createElement("div");
    text.className = "note-text";
    text.textContent = note.text;
    item.append(text);
  }

  const toolbar = doc.createElement("div");
  toolbar.className = "note-toolbar";
  const pin = toolbarButton(doc, "pin", note.pinned ? "Unpin" : "Pin");
  pin.setAttribute("aria-pressed", String(note.pinned));
  toolbar.append(pin, toolbarButton(doc, "delete", "Delete"));
  item.append(toolbar);
  return item;
}

/**
 * Mounts the board. `initialNotes` are the loaded notes; `newId` returns a
 * fresh unique id. Returns nothing: the board lives in its listeners.
 */
export function mountBoard({ doc, storage, list, addButton, toaster, initialNotes, newId }) {
  const board = {
    notes: initialNotes,
    editingId: NOT_EDITING,
    draft: "",
    modal: NO_MODAL,
  };

  function persist(notes) {
    saveNotes(storage, notes);
    board.notes = notes;
  }

  function itemFor(id) {
    const item = Array.from(list.children).find((child) => child.dataset.noteId === id);
    if (item === undefined) {
      throw new Error(`note ${JSON.stringify(id)} is not on the page`);
    }
    return item;
  }

  function renderOne(id) {
    const note = findNote(board.notes, id);
    const editing = board.editingId === id;
    const item = renderNote(doc, note, editing, board.draft);
    itemFor(id).replaceWith(item);
    return item;
  }

  function renderAll() {
    const items = displayOrder(board.notes).map((note) =>
      renderNote(doc, note, board.editingId === note.id, board.draft),
    );
    list.replaceChildren(...items);
    list.classList.toggle("empty", items.length === 0);
  }

  function focusEditor(item) {
    const area = item.querySelector("textarea");
    area.focus();
    area.setSelectionRange(area.value.length, area.value.length);
  }

  function enterEdit(id) {
    board.editingId = id;
    board.draft = findNote(board.notes, id).text;
    focusEditor(renderOne(id));
  }

  /** Saves the note being edited and leaves edit mode. */
  function commitEdit() {
    const id = board.editingId;
    persist(updateText(board.notes, id, board.draft));
    board.editingId = NOT_EDITING;
    renderOne(id);
    toaster.show("Saved", { autoHide: true });
  }

  function cancelEdit() {
    const id = board.editingId;
    board.editingId = NOT_EDITING;
    renderOne(id);
  }

  function saveIfLeaving(target) {
    const decision = decidePress({
      editingId: board.editingId,
      pressedNoteId: noteIdOf(target),
      onOverlay: isOnOverlay(target),
    });
    if (decision === PRESS.SAVE) {
      commitEdit();
    }
  }

  function confirmDelete(id) {
    board.modal = openConfirm(doc, {
      message: "Delete this note? This cannot be undone.",
      confirmLabel: "Delete",
      onConfirm: () => {
        if (board.editingId === id) {
          board.editingId = NOT_EDITING;
        }
        persist(removeNote(board.notes, id));
        renderAll();
      },
      onClose: () => {
        board.modal = NO_MODAL;
      },
    });
  }

  // A press outside the note being edited saves it. Only that note is
  // re-rendered, so the element under the pointer stays in place and the
  // click that follows still reaches its button.
  doc.addEventListener("pointerdown", (event) => saveIfLeaving(event.target), {
    capture: true,
  });

  doc.addEventListener("keydown", (event) => {
    const decision = decideKey({
      key: event.key,
      editingId: board.editingId,
      modalOpen: board.modal !== NO_MODAL,
    });
    if (decision === KEY.CLOSE_MODAL) {
      board.modal.close();
    } else if (decision === KEY.CANCEL_EDIT) {
      event.preventDefault();
      cancelEdit();
    }
  });

  list.addEventListener("input", (event) => {
    if (event.target instanceof Element && event.target.matches("textarea.note-editor")) {
      board.draft = event.target.value;
    }
  });

  // One delegated listener for the notes and their toolbar buttons.
  list.addEventListener("click", (event) => {
    // Keyboard activation sends a click without a press first.
    saveIfLeaving(event.target);
    const noteId = noteIdOf(event.target);
    const decision = decideListClick({
      noteId,
      action: actionOf(event.target),
      editingId: board.editingId,
    });
    if (decision === LIST_CLICK.EDIT) {
      enterEdit(noteId);
    } else if (decision === LIST_CLICK.PIN) {
      persist(togglePin(board.notes, noteId));
      renderAll();
      if (board.editingId !== NOT_EDITING) {
        focusEditor(itemFor(board.editingId));
      }
    } else if (decision === LIST_CLICK.DELETE) {
      confirmDelete(noteId);
    }
  });

  addButton.addEventListener("click", (event) => {
    saveIfLeaving(event.target);
    const note = createNote(newId(), "");
    persist(addNote(board.notes, note));
    renderAll();
    enterEdit(note.id);
  });

  renderAll();
}
