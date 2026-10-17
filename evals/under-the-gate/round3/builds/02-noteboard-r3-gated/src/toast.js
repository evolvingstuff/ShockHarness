// Toasts at the bottom of the page. Each toast owns its timer; closing it
// early clears the timer.

import { icon } from "./icons.js";

export function createToaster(doc, container, durationMs) {
  function show(message, options) {
    const toast = doc.createElement("div");
    toast.className = "toast";
    toast.setAttribute("role", "status");
    const text = doc.createElement("span");
    text.textContent = message;
    const close = doc.createElement("button");
    close.type = "button";
    close.className = "icon-button";
    close.setAttribute("aria-label", "Close");
    close.append(icon(doc, "close"));
    toast.append(text, close);

    let timer = null;
    function dismiss() {
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
      toast.remove();
    }
    close.addEventListener("click", dismiss);
    if (options.autoHide) {
      timer = setTimeout(dismiss, durationMs);
    }
    container.append(toast);
    return Object.freeze({ dismiss });
  }
  return Object.freeze({ show });
}
