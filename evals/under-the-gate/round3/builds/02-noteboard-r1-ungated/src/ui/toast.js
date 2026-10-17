import { CLOSE } from './icons.js';

let region = null;

function getRegion() {
  if (!region || !region.isConnected) {
    region = document.createElement('div');
    region.className = 'toasts';
    region.dataset.overlay = '';
    region.setAttribute('role', 'status');
    region.setAttribute('aria-live', 'polite');
    document.body.append(region);
  }
  return region;
}

// Shows a toast. `duration` in ms; pass 0 to keep it until closed.
export function showToast(message, { duration = 3000, kind = 'info' } = {}) {
  const el = document.createElement('div');
  el.className = `toast toast-${kind}`;
  const text = document.createElement('span');
  text.textContent = message;
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'icon-btn';
  close.setAttribute('aria-label', 'Close');
  close.innerHTML = CLOSE;

  let timer = null;
  const dismiss = () => {
    clearTimeout(timer);
    el.remove();
  };
  close.addEventListener('click', dismiss);
  el.append(text, close);
  getRegion().append(el);
  if (duration > 0) timer = setTimeout(dismiss, duration);
  return dismiss;
}
