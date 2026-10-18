import { produces } from "./vendor/shockharness-contracts.js";

export function escapeHtml(text) {
  return produces(String(text).replace(/[&<>"']/g, ""), "escaped_html");
}
