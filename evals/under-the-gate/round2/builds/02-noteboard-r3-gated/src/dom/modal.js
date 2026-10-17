// A confirmation dialog, created when needed and attached to <body>. Its buttons have their
// own listeners, so they work regardless of the board's edit mode.

export function openConfirm(doc, request) {
  const dialog = doc.createElement("dialog");
  dialog.className = "confirm";
  const message = doc.createElement("p");
  message.textContent = request.message;
  const buttons = doc.createElement("div");
  buttons.className = "dialog-buttons";
  const cancel = doc.createElement("button");
  cancel.type = "button";
  cancel.textContent = "Cancel";
  const confirm = doc.createElement("button");
  confirm.type = "button";
  confirm.className = "danger";
  confirm.textContent = request.confirmLabel;
  buttons.append(cancel, confirm);
  dialog.append(message, buttons);

  dialog.addEventListener("close", () => dialog.remove());
  cancel.addEventListener("click", () => dialog.close());
  confirm.addEventListener("click", () => {
    dialog.close();
    request.onConfirm();
  });

  doc.body.append(dialog);
  dialog.showModal();
  cancel.focus();
}

export function isDialogOpen(doc) {
  return doc.querySelector("dialog[open]") !== null;
}
