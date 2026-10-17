// Toasts at the bottom of the page, each with a close button.

import { OVERLAY_ATTRIBUTE } from "./overlay.js";

export function createToaster(doc, container, durationMs) {
  container.setAttribute(OVERLAY_ATTRIBUTE, "");

  function show(message, className) {
    const toast = doc.createElement("div");
    toast.className = `toast ${className}`;
    toast.setAttribute("role", className === "toast-problem" ? "alert" : "status");
    const text = doc.createElement("span");
    text.textContent = message;
    const close = doc.createElement("button");
    close.type = "button";
    close.className = "toast-close";
    close.setAttribute("aria-label", "Close");
    close.textContent = "×";
    toast.append(text, close);
    container.append(toast);
    return { toast, close };
  }

  /** A toast that disappears on its own after the configured duration. */
  function showBrief(message) {
    const { toast, close } = show(message, "toast-brief");
    const timer = setTimeout(() => toast.remove(), durationMs);
    close.addEventListener("click", () => {
      clearTimeout(timer);
      toast.remove();
    });
  }

  /** A toast reporting a problem; it stays until the user closes it. */
  function showProblem(message) {
    const { toast, close } = show(message, "toast-problem");
    close.addEventListener("click", () => toast.remove());
  }

  return Object.freeze({ showBrief, showProblem });
}
