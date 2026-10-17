import { icon } from "./icons.js";

// Keyed rendering of the note list: each note keeps its <li> across renders, so a
// press that started on a note still lands on the same element when the click fires.

function toolbarButton(doc, action, label, pressed) {
  const button = doc.createElement("button");
  button.type = "button";
  button.className = "tool";
  button.dataset.action = action;
  button.setAttribute("aria-label", label);
  button.title = label;
  if (pressed !== null) {
    button.setAttribute("aria-pressed", String(pressed));
  }
  button.append(icon(doc, action));
  return button;
}

function fillNote(doc, li, note, editing) {
  li.replaceChildren();
  li.classList.toggle("pinned", note.pinned);
  li.classList.toggle("editing", editing);
  const toolbar = doc.createElement("div");
  toolbar.className = "toolbar";
  toolbar.append(
    toolbarButton(doc, "pin", note.pinned ? "Unpin note" : "Pin note", note.pinned),
    toolbarButton(doc, "delete", "Delete note", null),
  );
  if (editing) {
    const textarea = doc.createElement("textarea");
    textarea.className = "note-editor";
    textarea.value = note.text;
    textarea.setAttribute("aria-label", "Note text");
    li.append(textarea, toolbar);
    return;
  }
  const text = doc.createElement("p");
  text.className = "note-text";
  text.textContent = note.text;
  li.append(text, toolbar);
}

export function createBoardView(doc, list) {
  const items = new Map();
  const signatures = new WeakMap();

  function render(orderedNotes, editingId) {
    const visible = new Set(orderedNotes.map((note) => note.id));
    for (const [id, li] of items) {
      if (!visible.has(id)) {
        li.remove();
        items.delete(id);
      }
    }
    for (const note of orderedNotes) {
      if (!items.has(note.id)) {
        const li = doc.createElement("li");
        li.className = "note";
        li.dataset.noteId = note.id;
        items.set(note.id, li);
      }
      const li = items.get(note.id);
      const editing = note.id === editingId;
      const signature = JSON.stringify([note.text, note.pinned, editing]);
      if (signatures.get(li) !== signature) {
        fillNote(doc, li, note, editing);
        signatures.set(li, signature);
      }
      list.append(li);
    }
  }

  function editorFor(id) {
    const editor = items.get(id).querySelector(".note-editor");
    if (editor === null) {
      throw new Error(`note ${id} is not in edit mode`);
    }
    return editor;
  }

  return Object.freeze({
    render,
    draftText: (id) => editorFor(id).value,
    focusEditor: (id) => editorFor(id).focus(),
  });
}
