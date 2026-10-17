// Confirmation dialog, created on demand and attached to <body>. It lives
// outside the notes list and is marked data-overlay so the board's
// outside-press handling leaves it alone.

/** Resolves to true if confirmed, false if cancelled. */
export function confirmDialog({ title, message, confirmLabel = 'OK', cancelLabel = 'Cancel' }) {
  return new Promise((resolve) => {
    const previousFocus = document.activeElement;

    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.dataset.overlay = '';

    const dialog = document.createElement('div');
    dialog.className = 'modal';
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('aria-labelledby', 'modal-title');

    const heading = document.createElement('h2');
    heading.id = 'modal-title';
    heading.textContent = title;

    const body = document.createElement('p');
    body.textContent = message;

    const actions = document.createElement('div');
    actions.className = 'modal-actions';
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.textContent = cancelLabel;
    const confirm = document.createElement('button');
    confirm.type = 'button';
    confirm.className = 'danger';
    confirm.textContent = confirmLabel;
    actions.append(cancel, confirm);

    dialog.append(heading, body, actions);
    backdrop.append(dialog);

    const close = (result) => {
      backdrop.remove();
      if (previousFocus && previousFocus.isConnected && typeof previousFocus.focus === 'function') {
        previousFocus.focus();
      }
      resolve(result);
    };

    cancel.addEventListener('click', () => close(false));
    confirm.addEventListener('click', () => close(true));
    backdrop.addEventListener('click', (e) => {
      if (e.target === backdrop) close(false);
    });
    backdrop.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        // Handled here so the board does not also treat it as "leave edit mode".
        e.stopPropagation();
        close(false);
      } else if (e.key === 'Tab') {
        // Keep focus inside the dialog.
        const first = cancel;
        const last = confirm;
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    });

    document.body.append(backdrop);
    cancel.focus();
  });
}
