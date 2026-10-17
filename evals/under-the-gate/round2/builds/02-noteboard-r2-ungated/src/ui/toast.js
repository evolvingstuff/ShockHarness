import { iconButton } from './icons.js';

export const TOAST_DURATION_MS = 3000;

let container = null;

function getContainer() {
  if (!container || !container.isConnected) {
    container = document.createElement('div');
    container.className = 'toasts';
    container.dataset.overlay = '';
    container.setAttribute('role', 'status');
    container.setAttribute('aria-live', 'polite');
    document.body.append(container);
  }
  return container;
}

/** Show a toast at the bottom of the page. Returns a function that closes it. */
export function showToast(message, { duration = TOAST_DURATION_MS, kind = 'info' } = {}) {
  const toast = document.createElement('div');
  toast.className = `toast toast-${kind}`;

  const text = document.createElement('span');
  text.className = 'toast-message';
  text.textContent = message;

  const close = iconButton('close', 'Close notification', { 'data-action': 'close-toast' });

  let timer = null;
  const dismiss = () => {
    clearTimeout(timer);
    toast.remove();
  };
  close.addEventListener('click', dismiss);
  if (duration > 0) timer = setTimeout(dismiss, duration);

  toast.append(text, close);
  getContainer().append(toast);
  return dismiss;
}
