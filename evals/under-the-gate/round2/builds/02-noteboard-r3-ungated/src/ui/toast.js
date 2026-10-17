// Toasts at the bottom of the page. Each toast owns its own timer, so a newer
// toast never cuts an older one short (or vice versa).

const DEFAULT_DURATION = 3000;
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

/**
 * Shows a toast. `duration` 0 keeps it until closed. A toast with a `tag`
 * replaces any visible toast with the same tag (e.g. repeated "Saved").
 */
export function showToast(message, { duration = DEFAULT_DURATION, tag = null, kind = 'info' } = {}) {
  const root = getContainer();
  if (tag) {
    for (const old of root.querySelectorAll('.toast')) {
      if (old.dataset.tag === tag) old._dismiss();
    }
  }

  const el = document.createElement('div');
  el.className = `toast toast-${kind}`;
  if (tag) el.dataset.tag = tag;

  const text = document.createElement('span');
  text.className = 'toast-message';
  text.textContent = message;

  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'toast-close';
  close.setAttribute('aria-label', 'Dismiss');
  close.textContent = '×';

  let timer = null;
  const dismiss = () => {
    clearTimeout(timer);
    el.remove();
  };
  el._dismiss = dismiss;
  close.addEventListener('click', dismiss);
  if (duration > 0) timer = setTimeout(dismiss, duration);

  el.append(text, close);
  root.append(el);
  return dismiss;
}
