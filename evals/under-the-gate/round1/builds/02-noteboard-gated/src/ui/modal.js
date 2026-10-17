import { el } from "./dom.js";

// Creates the dialog on demand and attaches it to the body; it is removed again
// when either button is pressed or Escape is pressed inside it.
export function confirmDialog(doc, message, onConfirm) {
  const cancel = el(doc, "button", { type: "button", "data-modal-action": "cancel" }, ["Cancel"]);
  const confirm = el(doc, "button", { type: "button", "data-modal-action": "confirm" }, ["Delete"]);
  const dialog = el(doc, "div", { class: "dialog", role: "dialog", "aria-modal": "true" }, [
    el(doc, "p", {}, [message]),
    cancel,
    confirm,
  ]);
  const overlay = el(doc, "div", { "data-modal": "" }, [dialog]);
  cancel.addEventListener("click", () => overlay.remove());
  confirm.addEventListener("click", () => {
    overlay.remove();
    onConfirm();
  });
  overlay.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    event.stopPropagation();
    overlay.remove();
  });
  doc.body.append(overlay);
  cancel.focus();
  return overlay;
}
