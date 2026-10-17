// Toasts at the bottom of the page. A transient toast removes itself; a sticky one waits to be closed.

export const TOAST_TRANSIENT = "transient";
export const TOAST_STICKY = "sticky";

export function createToaster(doc, durationMs) {
  const region = doc.createElement("div");
  region.className = "toasts";
  region.setAttribute("role", "status");
  region.setAttribute("aria-live", "polite");
  doc.body.append(region);

  function show(message, lifetime) {
    if (lifetime !== TOAST_TRANSIENT && lifetime !== TOAST_STICKY) {
      throw new RangeError(`unknown toast lifetime ${lifetime}`);
    }
    const toast = doc.createElement("div");
    toast.className = `toast ${lifetime}`;
    const text = doc.createElement("span");
    text.textContent = message;
    const close = doc.createElement("button");
    close.type = "button";
    close.className = "toast-close";
    close.setAttribute("aria-label", "Close");
    close.textContent = "×";
    toast.append(text, close);
    region.append(toast);

    if (lifetime === TOAST_TRANSIENT) {
      const timer = doc.defaultView.setTimeout(() => toast.remove(), durationMs);
      close.addEventListener("click", () => {
        doc.defaultView.clearTimeout(timer);
        toast.remove();
      });
    } else {
      close.addEventListener("click", () => toast.remove());
    }
  }

  return Object.freeze({ show });
}
