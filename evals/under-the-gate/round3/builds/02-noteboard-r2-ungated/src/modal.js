// Confirmation dialog, created on demand and attached to <body>.

let current = null; // { close(result) }

export function isModalOpen() {
  return current !== null;
}

export function closeModal(result = false) {
  if (current) current.close(result);
}

/** Resolves to true if confirmed, false otherwise. */
export function confirmDialog(message, { confirmLabel = 'Delete', cancelLabel = 'Cancel' } = {}) {
  if (current) current.close(false);

  return new Promise((resolve) => {
    const previousFocus = document.activeElement;

    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.dataset.overlay = '';

    const dialog = document.createElement('div');
    dialog.className = 'modal';
    dialog.setAttribute('role', 'alertdialog');
    dialog.setAttribute('aria-modal', 'true');

    const text = document.createElement('p');
    text.id = 'modal-message';
    text.textContent = message;
    dialog.setAttribute('aria-labelledby', text.id);

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
    backdrop.appendChild(dialog);

    const state = {
      close(result) {
        if (current !== state) return;
        current = null;
        backdrop.remove();
        if (previousFocus && previousFocus.isConnected) previousFocus.focus();
        resolve(result);
      },
    };
    current = state;

    cancel.addEventListener('click', () => state.close(false));
    confirm.addEventListener('click', () => state.close(true));
    backdrop.addEventListener('click', (e) => {
      if (e.target === backdrop) state.close(false);
    });

    document.body.appendChild(backdrop);
    cancel.focus();
  });
}
