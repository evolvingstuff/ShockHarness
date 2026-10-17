// Small helpers for reading events. `instanceof Element` (not HTMLElement) so
// that presses on the SVG icons inside buttons are recognised.

export function closestOf(target, selector) {
  if (!(target instanceof Element)) {
    return null;
  }
  return target.closest(selector);
}

export function noteIdOf(target) {
  const item = closestOf(target, "[data-note-id]");
  if (item === null) {
    return null;
  }
  return item.dataset.noteId;
}

export function actionOf(target) {
  const button = closestOf(target, "button[data-action]");
  if (button === null) {
    return null;
  }
  return button.dataset.action;
}

export function isOnOverlay(target) {
  return closestOf(target, "[data-overlay]") !== null;
}
