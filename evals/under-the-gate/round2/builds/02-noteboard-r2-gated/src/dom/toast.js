// Toasts at the bottom of the page. A toast either dismisses itself after a
// duration or stays until its close button is pressed.

import { markOverlay } from "./overlay.js";

export const DISMISS_AUTO = "auto";
export const DISMISS_MANUAL = "manual";

function toastRegion(doc) {
  const existing = doc.querySelector(".toast-region");
  if (existing !== null) {
    return existing;
  }
  const region = doc.createElement("div");
  region.className = "toast-region";
  region.setAttribute("role", "status");
  region.setAttribute("aria-live", "polite");
  markOverlay(region);
  doc.body.append(region);
  return region;
}

/** dismissal: { kind: DISMISS_AUTO, durationMs } or { kind: DISMISS_MANUAL }. */
export function showToast(doc, view, message, dismissal) {
  const toast = doc.createElement("div");
  toast.className = "toast";
  const text = doc.createElement("span");
  text.textContent = message;
  const close = doc.createElement("button");
  close.type = "button";
  close.className = "toast-close";
  close.setAttribute("aria-label", "Close");
  close.textContent = "×";
  toast.append(text, close);

  let timer = null;
  const dismiss = () => {
    if (timer !== null) {
      view.clearTimeout(timer);
    }
    toast.remove();
  };
  close.addEventListener("click", dismiss);
  toastRegion(doc).append(toast);

  if (dismissal.kind === DISMISS_AUTO) {
    timer = view.setTimeout(dismiss, dismissal.durationMs);
  } else if (dismissal.kind !== DISMISS_MANUAL) {
    throw new RangeError(`unknown toast dismissal ${dismissal.kind}`);
  }
  return toast;
}
