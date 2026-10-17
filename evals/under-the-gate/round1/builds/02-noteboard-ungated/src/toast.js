export function showToast(doc, message, { duration = 3000 } = {}) {
  let host = doc.getElementById('toasts');
  if (!host) {
    host = doc.createElement('div');
    host.id = 'toasts';
    doc.body.appendChild(host);
  }
  const el = doc.createElement('div');
  el.className = 'toast';
  el.setAttribute('role', 'status');
  const text = doc.createElement('span');
  text.textContent = message;
  const close = doc.createElement('button');
  close.type = 'button';
  close.className = 'toast-close';
  close.setAttribute('aria-label', 'Close');
  close.textContent = '×';
  const dismiss = () => { clearTimeout(timer); el.remove(); };
  close.addEventListener('click', dismiss);
  el.append(text, close);
  host.appendChild(el);
  const timer = setTimeout(dismiss, duration);
  return dismiss;
}
