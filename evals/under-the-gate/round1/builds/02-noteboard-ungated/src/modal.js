// Creates a confirm dialog on demand, attaches it to the page, resolves a promise.
export function confirmDialog(doc, message) {
  return new Promise((resolve) => {
    const overlay = doc.createElement('div');
    overlay.className = 'modal-overlay';
    const box = doc.createElement('div');
    box.className = 'modal';
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    const p = doc.createElement('p');
    p.textContent = message;
    const cancel = doc.createElement('button');
    cancel.type = 'button';
    cancel.textContent = 'Cancel';
    const ok = doc.createElement('button');
    ok.type = 'button';
    ok.textContent = 'Delete';
    ok.className = 'danger';
    const done = (v) => { overlay.remove(); resolve(v); };
    cancel.addEventListener('click', () => done(false));
    ok.addEventListener('click', () => done(true));
    box.append(p, cancel, ok);
    overlay.appendChild(box);
    doc.body.appendChild(overlay);
    ok.focus();
  });
}
