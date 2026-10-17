import { CLOSE } from './icons.js';

const DEFAULT_MS = 3000;

/** Shows a toast at the bottom of the page. Returns a function that hides it. */
export function showToast(message, { duration = DEFAULT_MS, kind = 'info' } = {}) {
  let region = document.getElementById('toasts');
  if (!region) {
    region = document.createElement('div');
    region.id = 'toasts';
    region.className = 'toasts';
    region.setAttribute('data-overlay', '');
    document.body.appendChild(region);
  }

  const toast = document.createElement('div');
  toast.className = `toast toast-${kind}`;
  toast.setAttribute('role', kind === 'error' ? 'alert' : 'status');

  const text = document.createElement('span');
  text.textContent = message;
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'icon-button';
  close.setAttribute('aria-label', 'Dismiss');
  close.innerHTML = CLOSE;

  toast.append(text, close);
  region.appendChild(toast);

  let timer = null;
  const hide = () => {
    clearTimeout(timer);
    toast.remove();
  };
  close.addEventListener('click', hide);
  if (duration > 0) timer = setTimeout(hide, duration);
  return hide;
}
