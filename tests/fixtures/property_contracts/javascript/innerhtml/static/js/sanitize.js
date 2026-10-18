import DOMPurify from "dompurify";
import { produces } from "./vendor/shockharness-contracts.js";

export function sanitize(markup) {
  return produces(DOMPurify.sanitize(markup), "sanitized_html");
}
