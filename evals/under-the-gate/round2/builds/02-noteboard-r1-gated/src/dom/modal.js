// A confirmation dialog, created when needed and attached to the page.

import { ESCAPE_KEY } from "../editMode.js";
import { OVERLAY_ATTRIBUTE } from "./overlay.js";

const MODAL_ATTRIBUTE = "data-modal";

export function isModalOpen(doc) {
  return doc.querySelector(`[${MODAL_ATTRIBUTE}]`) !== null;
}

function createButton(doc, label, className) {
  const button = doc.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = label;
  return button;
}

/** Shows a modal asking `message`; calls exactly one of onConfirm or onCancel, then removes itself. */
export function openConfirm(doc, { message, confirmLabel, onConfirm, onCancel }) {
  if (isModalOpen(doc)) {
    throw new Error("a modal is already open");
  }
  const backdrop = doc.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.setAttribute(MODAL_ATTRIBUTE, "");
  backdrop.setAttribute(OVERLAY_ATTRIBUTE, "");

  const dialog = doc.createElement("div");
  dialog.className = "modal";
  dialog.setAttribute("role", "alertdialog");
  dialog.setAttribute("aria-modal", "true");
  const text = doc.createElement("p");
  text.id = "modal-message";
  text.textContent = message;
  dialog.setAttribute("aria-labelledby", text.id);
  const cancel = createButton(doc, "Cancel", "modal-cancel");
  const confirm = createButton(doc, confirmLabel, "modal-confirm");
  const actions = doc.createElement("div");
  actions.className = "modal-actions";
  actions.append(cancel, confirm);
  dialog.append(text, actions);
  backdrop.append(dialog);

  function close(callback) {
    backdrop.remove();
    callback();
  }

  cancel.addEventListener("click", () => close(onCancel));
  confirm.addEventListener("click", () => close(onConfirm));
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) close(onCancel);
  });
  backdrop.addEventListener("keydown", (event) => {
    if (event.key === ESCAPE_KEY) {
      event.stopPropagation();
      close(onCancel);
    }
  });

  doc.body.append(backdrop);
  cancel.focus();
}
