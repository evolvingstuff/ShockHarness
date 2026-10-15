// Response bodies: decoding is the one boundary; every failure is a ParseError.

export class ParseError extends Error {
  constructor(message, options) {
    super(message, options);
    this.name = "ParseError";
  }
}

export function parseBody(text) {
  let data;
  // Boundary (declared in .shockharness.toml): decoding external input.
  try {
    data = JSON.parse(text);
  } catch (err) {
    if (!(err instanceof SyntaxError)) throw err;
    throw new ParseError(`malformed body: ${err.message}`, { cause: err });
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    throw new ParseError(`body must be a JSON object, got ${text}`, {});
  }
  return data;
}

export function loadAll(loaders) {
  return Promise.all(loaders.map((load) => load()));
}
