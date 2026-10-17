const svg = (body) =>
  `<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;

export const PIN = svg('<path d="M12 17v5"/><path d="M9 3h6l-1 7 4 4H6l4-4z"/>');
export const TRASH = svg('<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M6 6l1 14h10l1-14"/>');
export const CLOSE = svg('<path d="M6 6l12 12M18 6L6 18"/>');
