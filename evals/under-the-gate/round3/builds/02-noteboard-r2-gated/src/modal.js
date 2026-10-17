// Confirmation modal, created on demand and attached to <body>. It is removed when closed.

export function confirmModal(doc, message, confirmLabel, onConfirm) {
  const dialog = doc.createElement("dialog");
  dialog.className = "modal";
  const text = doc.createElement("p");
  text.textContent = message;
  const buttons = doc.createElement("div");
  buttons.className = "modal-buttons";
  const cancel = doc.createElement("button");
  cancel.type = "button";
  cancel.textContent = "Cancel";
  const confirm = doc.createElement("button");
  confirm.type = "button";
  confirm.className = "danger";
  confirm.textContent = confirmLabel;
  buttons.append(cancel, confirm);
  dialog.append(text, buttons);

  cancel.addEventListener("click", () => dialog.close());
  confirm.addEventListener("click", () => {
    dialog.close();
    onConfirm();
  });
  dialog.addEventListener("close", () => dialog.remove());

  doc.body.append(dialog);
  dialog.showModal();
  cancel.focus();
}
