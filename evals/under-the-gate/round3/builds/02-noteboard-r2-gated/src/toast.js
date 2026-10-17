// Toasts at the bottom of the page. Each closes itself after durationMs or on its close button.

export function createToaster(doc, container, durationMs) {
  function show(message) {
    const toast = doc.createElement("div");
    toast.className = "toast";
    toast.setAttribute("role", "status");
    const text = doc.createElement("span");
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
    container.append(toast);
  }

  return Object.freeze({ show });
}
