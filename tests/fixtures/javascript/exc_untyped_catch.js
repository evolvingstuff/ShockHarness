function load(raw) {
  try {
    return JSON.parse(raw);
  } catch (err) {
    console.error("bad json", err);
  }
}

function loadNoBinding(raw) {
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

function loadDestructured(raw) {
  try {
    return JSON.parse(raw);
  } catch ({ message }) {
    throw new Error(message);
  }
}

function nameCheckIsNotAGuard(raw) {
  try {
    return JSON.parse(raw);
  } catch (err) {
    if (err.name !== "SyntaxError") throw err;
    return null;
  }
}
