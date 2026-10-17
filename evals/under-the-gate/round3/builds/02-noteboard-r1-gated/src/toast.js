// Toasts at the bottom of the page: they close on their own after a while, or
// with their close button.

import { TOAST_REGION_CLASS } from "./floating.js";

function toastRegion(doc) {
  const existing = doc.querySelector(`.${TOAST_REGION_CLASS}`);
  if (existing !== null) {
    return existing;
  }
  const region = doc.createElement("div");
  region.className = TOAST_REGION_CLASS;
  region.setAttribute("role", "status");
  region.setAttribute("aria-live", "polite");
  doc.body.append(region);
  return region;
}

export function showToast(doc, message, durationMs) {
  const toast = doc.createElement("div");
  toast.className = "toast";
  const text = doc.createElement("span");
  text.className = "toast-message";
  text.textContent = message;
  const close = doc.createElement("button");
  close.type = "button";
  close.className = "toast-close";
  close.setAttribute("aria-label", "Close");
  close.textContent = "×";
  toast.append(text, close);

  const timer = doc.defaultView.setTimeout(() => toast.remove(), durationMs);
  close.addEventListener("click", () => {
    doc.defaultView.clearTimeout(timer);
    toast.remove();
  });
  toastRegion(doc).append(toast);
}
