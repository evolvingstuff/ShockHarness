import { el } from "./dom.js";

function toastContainer(doc) {
  const existing = doc.getElementById("toasts");
  if (existing !== null) return existing;
  const container = el(doc, "div", { id: "toasts" }, []);
  doc.body.append(container);
  return container;
}

export function showToast(doc, text, durationMs) {
  const win = doc.defaultView;
  const close = el(doc, "button", { type: "button", "aria-label": "Close" }, ["×"]);
  const toast = el(doc, "div", { "data-toast": "", role: "status" }, [text, close]);
  const timer = win.setTimeout(() => toast.remove(), durationMs);
  close.addEventListener("click", () => {
    win.clearTimeout(timer);
    toast.remove();
  });
  toastContainer(doc).append(toast);
  return toast;
}
