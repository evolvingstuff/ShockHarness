// Rendering of the note list. Note elements are kept per id and updated in
// place, so a re-render between a press and its click never removes the
// button being clicked.

import { createIcon } from "./icons.js";

const TOOLBAR_ACTIONS = Object.freeze([
  Object.freeze({ action: "pin", label: "Pin" }),
  Object.freeze({ action: "delete", label: "Delete" }),
]);

function createNoteElement(doc, id) {
  const item = doc.createElement("li");
  item.className = "note";
  item.dataset.noteId = id;
  const body = doc.createElement("div");
  body.className = "note-body";
  const toolbar = doc.createElement("div");
  toolbar.className = "note-toolbar";
  for (const { action, label } of TOOLBAR_ACTIONS) {
    const button = doc.createElement("button");
    button.type = "button";
    button.dataset.action = action;
    button.setAttribute("aria-label", label);
    button.title = label;
    button.append(createIcon(doc, action));
    toolbar.append(button);
  }
  item.append(body, toolbar);
  return item;
}

function renderBody(doc, body, note, editing) {
  const isEdited = editing.noteId === note.id;
  const current = body.firstElementChild;
  if (isEdited) {
    if (current !== null && current.tagName === "TEXTAREA") {
      return;
    }
    const textarea = doc.createElement("textarea");
    textarea.className = "note-editor";
    textarea.setAttribute("aria-label", "Note text");
    textarea.value = editing.draft;
    body.replaceChildren(textarea);
    textarea.focus();
    return;
  }
  const text = doc.createElement("p");
  text.className = "note-text";
  text.textContent = note.text;
  body.replaceChildren(text);
}

/** Brings list in line with notes (already in display order) and the editing state. */
export function renderBoard(doc, list, notes, editing) {
  const existing = new Map(
    Array.from(list.children, (element) => [element.dataset.noteId, element]),
  );
  const wanted = notes.map((note) => {
    const element = existing.has(note.id) ? existing.get(note.id) : createNoteElement(doc, note.id);
    element.classList.toggle("pinned", note.pinned);
    element.classList.toggle("editing", editing.noteId === note.id);
    const pin = element.querySelector('[data-action="pin"]');
    pin.setAttribute("aria-pressed", String(note.pinned));
    renderBody(doc, element.querySelector(".note-body"), note, editing);
    return element;
  });
  const keep = new Set(wanted);
  for (const element of existing.values()) {
    if (!keep.has(element)) {
      element.remove();
    }
  }
  wanted.forEach((element, index) => {
    if (list.children[index] !== element) {
      list.insertBefore(element, list.children[index]);
    }
  });
}

/** The id of the note element containing target, or null. */
export function noteIdAt(target) {
  const note = target.closest(".note");
  if (note === null) {
    return null;
  }
  return note.dataset.noteId;
}
