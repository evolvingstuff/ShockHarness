function nested(path) {
  try {
    return readSync(path);
  } catch (outer) {
    try {
      return readFallback(path);
    } catch (inner) {
      console.error(outer, inner);
    }
    throw outer;
  }
}

function finallyOnly(path) {
  try {
    return readSync(path);
  } finally {
    cleanup(path);
  }
}

const inCallback = items.map((item) => {
  try {
    return parse(item);
  } catch (err) {
    return null;
  }
});
