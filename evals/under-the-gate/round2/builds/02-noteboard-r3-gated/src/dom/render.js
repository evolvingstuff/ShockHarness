import { icon } from "./icons.js";

export const ACTION_PIN = "pin";
export const ACTION_DELETE = "delete";

function toolButton(doc, action, label) {
  const button = doc.createElement("button");
  button.type = "button";
  button.className = "tool";
  button.dataset.action = action;
  button.title = label;
  button.setAttribute("aria-label", label);
  button.append(icon(doc, action));
  return button;
}

/** One note as an <li>; the note being edited shows a textarea holding the draft. */
export function renderNote(doc, note, editing) {
  const item = doc.createElement("li");
  item.className = "note";
  item.dataset.id = note.id;
  item.classList.toggle("pinned", note.pinned);
  const isEditing = editing.active && editing.id === note.id;
  item.classList.toggle("editing", isEditing);

  const toolbar = doc.createElement("div");
  toolbar.className = "toolbar";
  const pinButton = toolButton(doc, ACTION_PIN, note.pinned ? "Unpin" : "Pin");
  pinButton.setAttribute("aria-pressed", String(note.pinned));
  toolbar.append(pinButton, toolButton(doc, ACTION_DELETE, "Delete"));

  if (isEditing) {
    const area = doc.createElement("textarea");
    area.className = "editor";
    area.value = editing.draft;
    area.setAttribute("aria-label", "Note text");
    item.append(area, toolbar);
  } else {
    const body = doc.createElement("div");
    body.className = "text";
    body.textContent = note.text;
    item.append(body, toolbar);
  }
  return item;
}

export function renderList(doc, list, orderedNotes, editing) {
  list.replaceChildren(...orderedNotes.map((note) => renderNote(doc, note, editing)));
}

/** Re-renders a single note in place, leaving every other element of the list untouched. */
export function rerenderNote(doc, list, note, editing) {
  const current = [...list.children].find((child) => child.dataset.id === note.id);
  if (current === undefined) {
    throw new RangeError(`note ${note.id} is not on the page`);
  }
  current.replaceWith(renderNote(doc, note, editing));
}

export function editorOf(list) {
  const area = list.querySelector("li.editing textarea");
  if (area === null) {
    throw new Error("no note editor is on the page");
  }
  return area;
}
