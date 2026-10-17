const svg = (body) =>
  `<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;

export const ICONS = {
  pin: svg('<path d="M12 17v5"/><path d="M9 3h6l-1 6 4 4H6l4-4z"/>'),
  delete: svg('<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M6 6l1 14h10l1-14"/>'),
  close: svg('<path d="M6 6l12 12"/><path d="M18 6L6 18"/>'),
};
