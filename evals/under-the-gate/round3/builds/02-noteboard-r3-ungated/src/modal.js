// Confirmation dialog, created on demand and attached to <body>.
//
// It lives outside the notes list, so re-rendering the list (for example when
// a press outside the edited note saves it) never touches the dialog, and its
// buttons work whether or not a note is being edited.

let open = null;

export function isModalOpen() {
  return open !== null;
}

/** Shows a modal confirmation. Resolves to true (confirm) or false. */
export function confirmDialog(message, { confirmLabel = 'Delete', cancelLabel = 'Cancel' } = {}) {
  if (open) open.finish(false);

  return new Promise((resolve) => {
    const previousFocus = document.activeElement;
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    const dialog = document.createElement('div');
    dialog.className = 'modal';
    dialog.setAttribute('role', 'alertdialog');
    dialog.setAttribute('aria-modal', 'true');
    const text = document.createElement('p');
    text.id = 'modal-message';
    text.textContent = message;
    dialog.setAttribute('aria-describedby', text.id);

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
    dialog.append(text, actions);
    backdrop.append(dialog);

    // Capture phase on window so the dialog sees keys before the board does;
    // the board ignores events whose default was prevented.
    const onKey = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        finish(false);
      } else if (e.key === 'Tab') {
        // Keep focus inside the dialog.
        const items = [cancel, confirm];
        const i = items.indexOf(document.activeElement);
        const next = e.shiftKey ? (i <= 0 ? items.length - 1 : i - 1) : (i + 1) % items.length;
        e.preventDefault();
        items[next].focus();
      }
    };

    function finish(result) {
      if (open !== handle) return;
      open = null;
      window.removeEventListener('keydown', onKey, true);
      backdrop.remove();
      if (previousFocus && previousFocus.isConnected) previousFocus.focus();
      resolve(result);
    }
    const handle = { finish };

    cancel.addEventListener('click', () => finish(false));
    confirm.addEventListener('click', () => finish(true));
    backdrop.addEventListener('click', (e) => {
      if (e.target === backdrop) finish(false);
    });
    window.addEventListener('keydown', onKey, true);

    open = handle;
    document.body.append(backdrop);
    cancel.focus();
  });
}
