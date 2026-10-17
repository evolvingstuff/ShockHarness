// A confirmation dialog, created when needed and attached to document.body.
// Its buttons have their own listeners, so they work whatever the board is doing.

export function openConfirm(doc, { message, confirmLabel, onConfirm, onClose }) {
  const backdrop = doc.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.dataset.overlay = "modal";
  const dialog = doc.createElement("div");
  dialog.className = "modal";
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  const text = doc.createElement("p");
  text.textContent = message;
  const cancel = doc.createElement("button");
  cancel.type = "button";
  cancel.textContent = "Cancel";
  const confirm = doc.createElement("button");
  confirm.type = "button";
  confirm.className = "danger";
  confirm.textContent = confirmLabel;
  const buttons = doc.createElement("div");
  buttons.className = "modal-buttons";
  buttons.append(cancel, confirm);
  dialog.append(text, buttons);
  backdrop.append(dialog);

  let open = true;
  function close() {
    if (!open) {
      return;
    }
    open = false;
    backdrop.remove();
    onClose();
  }
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

  doc.body.append(backdrop);
  confirm.focus();
  return Object.freeze({ close });
}
