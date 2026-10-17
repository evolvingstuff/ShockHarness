// Rendering of notes into list items.

import { createIcon } from "./icons.js";

export const NOTE_SELECTOR = "[data-note-id]";
export const ACTION_SELECTOR = "button[data-action]";
export const ACTION = Object.freeze({ PIN: "pin", DELETE: "delete" });

function toolbarButton(doc, action, label) {
  const button = doc.createElement("button");
  button.type = "button";
  button.dataset.action = action;
  button.setAttribute("aria-label", label);
  button.title = label;
  button.append(createIcon(doc, action));
  return button;
}

/** session decides whether this note renders as an editor holding the draft. */
export function renderNote(doc, note, session) {
  const item = doc.createElement("li");
  item.className = "note";
  item.dataset.noteId = note.id;
  item.classList.toggle("pinned", note.pinned);

  const toolbar = doc.createElement("div");
  toolbar.className = "note-toolbar";
  const pin = toolbarButton(doc, ACTION.PIN, note.pinned ? "Unpin" : "Pin");
  pin.setAttribute("aria-pressed", String(note.pinned));
  toolbar.append(pin, toolbarButton(doc, ACTION.DELETE, "Delete"));

  if (session.editingId === note.id) {
    const editor = doc.createElement("textarea");
    editor.className = "note-editor";
    editor.value = session.draft;
    editor.setAttribute("aria-label", "Note text");
    item.classList.add("editing");
    item.append(toolbar, editor);
    return item;
  }
  const text = doc.createElement("p");
  text.className = "note-text";
  text.textContent = note.text;
  item.append(toolbar, text);
  return item;
}
