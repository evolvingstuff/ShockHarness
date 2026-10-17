import { ICONS } from './icons.js';

let container = null;

function getContainer() {
  if (!container || !container.isConnected) {
    container = document.createElement('div');
    container.className = 'toasts';
    container.dataset.overlay = '';
    container.setAttribute('role', 'status');
    container.setAttribute('aria-live', 'polite');
    document.body.appendChild(container);
  }
  return container;
}

/**
 * Show a toast at the bottom of the page. It removes itself after `timeout`
 * ms (0 = stays until closed) and always has a close button.
 */
export function showToast(message, { timeout = 3000, kind = 'info' } = {}) {
  const toast = document.createElement('div');
  toast.className = `toast toast-${kind}`;

  const text = document.createElement('span');
  text.textContent = message;

  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'icon-button';
  close.setAttribute('aria-label', 'Close notification');
  close.innerHTML = ICONS.close;

  let timer = null;
  const dismiss = () => {
    clearTimeout(timer);
    toast.remove();
  };
  close.addEventListener('click', dismiss);
  if (timeout > 0) timer = setTimeout(dismiss, timeout);

  toast.append(text, close);
  getContainer().appendChild(toast);
  return dismiss;
}
