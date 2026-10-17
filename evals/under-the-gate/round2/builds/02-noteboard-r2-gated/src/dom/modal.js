// A confirmation dialog, created when needed and attached to <body>. It is an
// overlay, so pressing its buttons never interacts with edit mode.

import { markOverlay } from "./overlay.js";

const CAPTURE = Object.freeze({ capture: true });

/** Calls onConfirm if the user confirms; closing in any other way does nothing. */
export function confirmDialog(doc, message, confirmLabel, onConfirm) {
  const backdrop = doc.createElement("div");
  backdrop.className = "modal-backdrop";
  markOverlay(backdrop);

  const dialog = doc.createElement("div");
  dialog.className = "modal";
  dialog.setAttribute("role", "alertdialog");
  dialog.setAttribute("aria-modal", "true");
  const text = doc.createElement("p");
  text.id = "modal-message";
  text.textContent = message;
  dialog.setAttribute("aria-describedby", text.id);

  const cancel = doc.createElement("button");
  cancel.type = "button";
  cancel.textContent = "Cancel";
  cancel.dataset.modalAction = "cancel";
  const confirm = doc.createElement("button");
  confirm.type = "button";
  confirm.className = "danger";
  confirm.textContent = confirmLabel;
  confirm.dataset.modalAction = "confirm";

  const buttons = doc.createElement("div");
  buttons.className = "modal-buttons";
  buttons.append(cancel, confirm);
  dialog.append(text, buttons);
  backdrop.append(dialog);

  const previousFocus = doc.activeElement;
  const close = () => {
    backdrop.remove();
    doc.removeEventListener("keydown", onKey, CAPTURE);
    if (previousFocus !== null && previousFocus.isConnected) {
      previousFocus.focus();
    }
  };
  const onKey = (event) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      close();
    }
  };
  cancel.addEventListener("click", close);
  confirm.addEventListener("click", () => {
    close();
    onConfirm();
  });
  backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) {
      close();
    }
  });
  doc.addEventListener("keydown", onKey, CAPTURE);

  doc.body.append(backdrop);
  confirm.focus();
  return backdrop;
}
