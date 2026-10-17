// Controls attached to document.body that handle their own presses. A press on
// one of them is never a press "outside" the note being edited.

export const MODAL_CLASS = "modal-backdrop";
export const TOAST_REGION_CLASS = "toast-region";

const FLOATING_SELECTOR = [`.${MODAL_CLASS}`, `.${TOAST_REGION_CLASS}`].join(",");

export function isFloatingControl(target) {
  return target instanceof Element && target.closest(FLOATING_SELECTOR) !== null;
}
