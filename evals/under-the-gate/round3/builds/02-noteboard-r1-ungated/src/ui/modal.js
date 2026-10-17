// Confirmation dialog, created on demand and attached to <body>.
// Resolves true (confirm) or false (cancel / Escape / backdrop).

let open = null;

export function isModalOpen() {
  return open !== null;
}

export function closeModal() {
  open?.(false);
}

export function confirmDialog({ message, confirmLabel = 'OK', cancelLabel = 'Cancel' }) {
  closeModal();
  return new Promise((resolve) => {
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.dataset.overlay = '';

    const dialog = document.createElement('div');
    dialog.className = 'modal';
    dialog.setAttribute('role', 'alertdialog');
    dialog.setAttribute('aria-modal', 'true');
    const msgId = `modal-msg-${Date.now()}`;
    dialog.setAttribute('aria-describedby', msgId);

    const p = document.createElement('p');
    p.id = msgId;
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
    backdrop.append(dialog);

    const previousFocus = document.activeElement;
    const finish = (result) => {
      if (open !== finish) return;
      open = null;
      backdrop.remove();
      if (previousFocus && previousFocus.isConnected) previousFocus.focus();
      resolve(result);
    };
    open = finish;

    ok.addEventListener('click', () => finish(true));
    cancel.addEventListener('click', () => finish(false));
    backdrop.addEventListener('click', (e) => {
      if (e.target === backdrop) finish(false);
    });
    // Keep Tab focus inside the dialog.
    dialog.addEventListener('keydown', (e) => {
      if (e.key !== 'Tab') return;
      const first = cancel;
      const last = ok;
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    });

    document.body.append(backdrop);
    cancel.focus();
  });
}
