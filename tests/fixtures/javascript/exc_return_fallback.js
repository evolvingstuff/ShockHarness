function nullFallback(raw) {
  try {
    return JSON.parse(raw);
  } catch (err) {
    return null;
  }
}

function undefinedFallback(raw) {
  try {
    return JSON.parse(raw);
  } catch (err) {
    return undefined;
  }
}

function bareReturn(raw) {
  try {
    return JSON.parse(raw);
  } catch (err) {
    return;
  }
}

function falseFallback(raw) {
  try {
    return JSON.parse(raw);
  } catch (err) {
    return false;
  }
}

function zeroFallback(raw) {
  try {
    return JSON.parse(raw);
  } catch (err) {
    return 0;
  }
}

function fabricated(raw) {
  try {
    return JSON.parse(raw);
  } catch (err) {
    console.error(err);
    return { items: [], total: 0, label: `none` };
  }
}

function notLiteral(raw, fallback) {
  try {
    return JSON.parse(raw);
  } catch (err) {
    return fallback;
  }
}

const arrowFallback = (raw) => Promise.resolve(raw).then(JSON.parse).catch((err) => null);
