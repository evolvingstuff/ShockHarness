function rethrow(raw) {
  try {
    return JSON.parse(raw);
  } catch (err) {
    throw err;
  }
}

function wrapWithCause(raw) {
  try {
    return JSON.parse(raw);
  } catch (err) {
    throw new ConfigError("bad json", { cause: err });
  }
}

function wrapShorthandCause(raw) {
  try {
    return JSON.parse(raw);
  } catch (cause) {
    throw new ConfigError("bad json", { cause });
  }
}

function wrapWithoutCause(raw) {
  try {
    return JSON.parse(raw);
  } catch (err) {
    throw new ConfigError("bad json");
  }
}

function logThenRethrow(raw) {
  try {
    return JSON.parse(raw);
  } catch (err) {
    console.warn(err);
    throw err;
  }
}
