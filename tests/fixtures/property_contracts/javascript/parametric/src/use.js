import { produces, requires } from "./vendor/contracts.js";
import { first, head, ident } from "./generic.js";

function deliver(text) {
  requires(text, "redacted");
  return text;
}

export function throughHead(raw, other) {
  const clean = produces(raw, "redacted");
  deliver(head(clean, 3));
  deliver(first(clean));
  deliver(head(other, 3));
  deliver(ident(clean));
}
