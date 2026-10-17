// Elements that float above the board (modal dialogs, toasts) carry this
// attribute so that a press inside them never counts as "outside the note".

export const OVERLAY_ATTRIBUTE = "data-overlay";

export function markOverlay(element) {
  element.setAttribute(OVERLAY_ATTRIBUTE, "");
}

export function isInOverlay(target) {
  return target.closest(`[${OVERLAY_ATTRIBUTE}]`) !== null;
}
