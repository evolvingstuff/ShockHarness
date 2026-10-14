// DEF005 traces: module constants and one-return helpers; imported names are not followed.
const EMPTY = [];
let mutable = {};
function fallbackRows() {
  return [];
}
const nothing = () => undefined;
const expressionBody = () => ({});
const notAHelper = () => compute();

function moduleConstant(raw) {
  try {
    return JSON.parse(raw);
  } catch (err) {
    return EMPTY;
  }
}

function letBinding(raw) {
  try {
    return JSON.parse(raw);
  } catch (err) {
    return mutable;
  }
}

function helper(raw) {
  try {
    return JSON.parse(raw);
  } catch (err) {
    console.error(err);
    return fallbackRows();
  }
}

function arrowHelpers(raw, which) {
  try {
    return JSON.parse(raw);
  } catch (err) {
    return which ? nothing() : expressionBody();
  }
}

function arrowHelper(raw) {
  try {
    return JSON.parse(raw);
  } catch (err) {
    return expressionBody();
  }
}

function fabricated(raw) {
  try {
    return JSON.parse(raw);
  } catch (err) {
    return new Map();
  }
}

function notTraced(raw) {
  try {
    return JSON.parse(raw);
  } catch (err) {
    return notAHelper();
  }
}

function imported(raw) {
  try {
    return JSON.parse(raw);
  } catch (err) {
    return IMPORTED_DEFAULT;
  }
}
