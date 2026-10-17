// Toasts at the bottom of the page.

export const TOAST_MS = 3000;

function container() {
  let el = document.getElementById('toasts');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toasts';
    el.className = 'toasts';
    el.setAttribute('role', 'status');
    el.setAttribute('aria-live', 'polite');
    document.body.append(el);
  }
  return el;
}

/**
 * Shows a toast. It disappears after `duration` ms; pass 0 to keep it until
 * the user closes it.
 */
export function showToast(message, { duration = TOAST_MS, kind = 'info' } = {}) {
  const toast = document.createElement('div');
  toast.className = `toast toast-${kind}`;
  const text = document.createElement('span');
  text.textContent = message;
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'toast-close';
  close.setAttribute('aria-label', 'Close');
  close.textContent = '×';

  let timer = null;
  const dismiss = () => {
    clearTimeout(timer);
    toast.remove();
  };
  close.addEventListener('click', dismiss);
  if (duration > 0) timer = setTimeout(dismiss, duration);

  toast.append(text, close);
  container().append(toast);
  return { element: toast, dismiss };
}
