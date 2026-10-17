// Renders the notes list. Elements are kept per note id and only the parts
// that changed are rebuilt, so a press that saves one note does not replace
// the button or note the same press landed on.

import { MODE_EDITING } from "../editMode.js";
import { createIcon } from "./icons.js";

export const ACTION_ATTRIBUTE = "data-action";
export const NOTE_ID_ATTRIBUTE = "data-note-id";

function createToolButton(action, label) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `tool tool-${action}`;
  button.setAttribute(ACTION_ATTRIBUTE, action);
  button.setAttribute("aria-label", label);
  button.title = label;
  button.append(createIcon(action));
  return button;
}

function createNoteElement(note) {
  const item = document.createElement("li");
  item.className = "note";
  item.setAttribute(NOTE_ID_ATTRIBUTE, note.id);
  const toolbar = document.createElement("div");
  toolbar.className = "note-toolbar";
  toolbar.append(createToolButton("pin", "Pin note"), createToolButton("delete", "Delete note"));
  const body = document.createElement("div");
  body.className = "note-body";
  item.append(toolbar, body);
  return item;
}

function fillBody(body, note, isEditing) {
  body.replaceChildren();
  if (isEditing) {
    body.removeAttribute(ACTION_ATTRIBUTE);
    const editor = document.createElement("textarea");
    editor.className = "note-editor";
    editor.setAttribute("aria-label", "Note text");
    editor.value = note.text;
    body.append(editor);
    return;
  }
  body.setAttribute(ACTION_ATTRIBUTE, "edit");
  body.textContent = note.text;
  body.classList.toggle("note-empty", note.text === "");
}

export function createBoardView(list, emptyMessage) {
  const elements = new Map();
  const bodySignatures = new Map();

  function editorFor(noteId) {
    const element = elements.get(noteId);
    if (element === undefined) {
      throw new RangeError(`no rendered note with id ${noteId}`);
    }
    const editor = element.querySelector(".note-editor");
    if (editor === null) {
      throw new Error(`note ${noteId} is not in edit mode`);
    }
    return editor;
  }

  function render(orderedNotes, edit) {
    const seen = new Set();
    orderedNotes.forEach((note) => {
      seen.add(note.id);
      if (!elements.has(note.id)) {
        elements.set(note.id, createNoteElement(note));
      }
      const element = elements.get(note.id);
      const isEditing = edit.mode === MODE_EDITING && edit.noteId === note.id;
      const signature = JSON.stringify([isEditing, note.text]);
      if (bodySignatures.get(note.id) !== signature) {
        fillBody(element.querySelector(".note-body"), note, isEditing);
        bodySignatures.set(note.id, signature);
      }
      element.classList.toggle("note-pinned", note.pinned);
      element.classList.toggle("note-editing", isEditing);
      const pin = element.querySelector(".tool-pin");
      pin.setAttribute("aria-pressed", String(note.pinned));
      pin.setAttribute("aria-label", note.pinned ? "Unpin note" : "Pin note");
      pin.title = pin.getAttribute("aria-label");
      list.append(element); // moves it into display order
    });
    [...elements.keys()].filter((id) => !seen.has(id)).forEach((id) => {
      elements.get(id).remove();
      elements.delete(id);
      bodySignatures.delete(id);
    });
    emptyMessage.hidden = orderedNotes.length > 0;
  }

  return Object.freeze({
    render,
    draftText: (noteId) => editorFor(noteId).value,
    focusEditor: (noteId) => editorFor(noteId).focus(),
    elementFor: (noteId) => elements.get(noteId),
  });
}
