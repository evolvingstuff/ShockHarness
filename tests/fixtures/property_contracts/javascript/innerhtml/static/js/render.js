import { escapeHtml } from "./html.js";
import { sanitize } from "./sanitize.js";

export function clear(el) {
  el.innerHTML = "";
}

export function escaped(el, tag) {
  el.innerHTML = `<b>${escapeHtml(tag)}</b>`;
}

export function sanitized(el, raw) {
  el.innerHTML = sanitize(raw);
}

export function interpolated(el, tag) {
  el.innerHTML = `<b>${tag}</b>`;
}

export function mixed(el, tag, raw) {
  el.innerHTML = `<b>${tag}</b>` + sanitize(raw);
}

export function joined(el, items) {
  el.innerHTML = `<ul>${items.map((i) => `<li>${escapeHtml(i)}</li>`).join("")}</ul>`;
}

export function concatenated(el, raw) {
  el.innerHTML = "<p>" + sanitize(raw) + "</p>";
}

export function noLiteral(el, a, b) {
  el.innerHTML = sanitize(a) + sanitize(b);
}

export function listed(el, a, b) {
  el.innerHTML = [sanitize(a), sanitize(b)].join("\n");
}

export function listedRaw(el, a, raw) {
  el.innerHTML = [sanitize(a), raw].join("");
}
