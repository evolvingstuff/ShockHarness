// A confirmation dialog, created when needed and attached to document.body.

import { MODAL_CLASS } from "./floating.js";

/** Shows the dialog; onConfirm runs only when the user confirms. */
export function confirmInModal(doc, options) {
  const backdrop = doc.createElement("div");
  backdrop.className = MODAL_CLASS;
  const dialog = doc.createElement("div");
  dialog.className = "modal";
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  const message = doc.createElement("p");
  message.textContent = options.message;
  const cancel = doc.createElement("button");
  cancel.type = "button";
  cancel.dataset.choice = "cancel";
  cancel.textContent = "Cancel";
  const confirm = doc.createElement("button");
  confirm.type = "button";
  confirm.dataset.choice = "confirm";
  confirm.className = "danger";
  confirm.textContent = options.confirmLabel;
  const buttons = doc.createElement("div");
  buttons.className = "modal-buttons";
  buttons.append(cancel, confirm);
  dialog.append(message, buttons);
  backdrop.append(dialog);

  function close() {
    doc.removeEventListener("keydown", onKey, { capture: true });
    backdrop.remove();
  }
  function onKey(event) {
    if (event.key === "Escape") {
      event.stopPropagation();
      close();
    }
  }
  cancel.addEventListener("click", close);
  confirm.addEventListener("click", () => {
    close();
    options.onConfirm();
  });
  doc.addEventListener("keydown", onKey, { capture: true });
  doc.body.append(backdrop);
  confirm.focus();
}
