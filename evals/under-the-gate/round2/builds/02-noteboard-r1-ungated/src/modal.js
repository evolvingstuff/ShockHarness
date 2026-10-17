/**
 * Asks for confirmation in a modal dialog created on demand and attached to
 * <body>, outside the board, so board-level handling never interferes with it.
 * Resolves true when confirmed, false otherwise.
 */
export function confirmDialog({ message, confirmLabel = 'Delete', cancelLabel = 'Cancel' }) {
  return new Promise((resolve) => {
    const dialog = document.createElement('dialog');
    dialog.className = 'modal';
    dialog.setAttribute('data-overlay', '');

    const p = document.createElement('p');
    p.textContent = message;

    const actions = document.createElement('div');
    actions.className = 'modal-actions';
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.textContent = cancelLabel;
    const ok = document.createElement('button');
    ok.type = 'button';
    ok.className = 'danger';
    ok.textContent = confirmLabel;
    actions.append(cancel, ok);
    dialog.append(p, actions);

    let result = false;
    const finish = (value) => {
      result = value;
      dialog.close();
    };
    cancel.addEventListener('click', () => finish(false));
    ok.addEventListener('click', () => finish(true));
    // Escape closes the dialog natively (fires 'cancel' then 'close').
    dialog.addEventListener('keydown', (e) => e.stopPropagation());
    dialog.addEventListener('close', () => {
      dialog.remove();
      resolve(result);
    });

    document.body.appendChild(dialog);
    dialog.showModal();
    cancel.focus();
  });
}

export function isModalOpen() {
  return document.querySelector('dialog.modal[open]') !== null;
}
