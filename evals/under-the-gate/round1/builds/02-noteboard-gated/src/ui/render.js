import { el, iconButton } from "./dom.js";
import { displayOrder } from "../notes.js";

const PIN_PATH = "M5 2h6M6 2v5L4 10h8L10 7V2M8 10v4";
const DELETE_PATH = "M3 4h10M6 4V2h4v2M5 4l1 10h4l1-10";

function noteBody(doc, note, isEditing, draft) {
  if (!isEditing) return el(doc, "p", {}, [note.text]);
  const area = el(doc, "textarea", { "aria-label": "Edit note" }, []);
  area.value = draft;
  return area;
}

function noteItem(doc, note, editingId, draft) {
  const isEditing = note.id === editingId;
  const toolbar = el(doc, "div", { class: "toolbar" }, [
    iconButton(doc, "pin", note.pinned ? "Unpin" : "Pin", PIN_PATH),
    iconButton(doc, "delete", "Delete", DELETE_PATH),
  ]);
  const attrs = { "data-note-id": String(note.id), class: note.pinned ? "pinned" : "" };
  return el(doc, "li", attrs, [noteBody(doc, note, isEditing, draft), toolbar]);
}

export function renderList(doc, listEl, notes, editingId, draft) {
  const items = displayOrder(notes).map((note) => noteItem(doc, note, editingId, draft));
  listEl.replaceChildren(...items);
}
