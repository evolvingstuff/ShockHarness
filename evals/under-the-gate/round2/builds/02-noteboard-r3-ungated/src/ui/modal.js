// Confirmation dialog. Created on demand, attached to <body>, removed on close.
// It handles its own clicks and keys, so it works regardless of board state.

let openCount = 0;

export function isModalOpen() {
  return openCount > 0;
}

/** Resolves true if confirmed, false if cancelled (button, backdrop or Escape). */
export function confirmDialog(message, { confirmLabel = 'Delete', cancelLabel = 'Cancel' } = {}) {
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
    text.className = 'modal-message';
    text.id = `modal-msg-${Date.now()}`;
    text.textContent = message;
    dialog.setAttribute('aria-describedby', text.id);

    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'modal-cancel';
    cancel.textContent = cancelLabel;

    const confirm = document.createElement('button');
    confirm.type = 'button';
    confirm.className = 'modal-confirm';
    confirm.textContent = confirmLabel;

    const actions = document.createElement('div');
    actions.className = 'modal-actions';
    actions.append(cancel, confirm);
    dialog.append(text, actions);
    backdrop.append(dialog);

    let done = false;
    const close = (result) => {
      if (done) return;
      done = true;
      openCount -= 1;
      document.removeEventListener('keydown', onKey, true);
      backdrop.remove();
      if (previousFocus && previousFocus.isConnected && typeof previousFocus.focus === 'function') {
        previousFocus.focus();
      }
      resolve(result);
    };

    // Capture phase on document: Escape goes to the modal even if focus
    // wandered, and never reaches the board's edit-mode handler.
    const onKey = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        close(false);
      } else if (e.key === 'Tab') {
        // Keep focus inside the dialog.
        const order = [cancel, confirm];
        const i = order.indexOf(document.activeElement);
        e.preventDefault();
        order[(i + (e.shiftKey ? order.length - 1 : 1)) % order.length].focus();
      }
    };

    cancel.addEventListener('click', () => close(false));
    confirm.addEventListener('click', () => close(true));
    backdrop.addEventListener('click', (e) => {
      if (e.target === backdrop) close(false);
    });
    document.addEventListener('keydown', onKey, true);

    openCount += 1;
    document.body.append(backdrop);
    confirm.focus();
  });
}
