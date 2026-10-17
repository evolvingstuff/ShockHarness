// Small type checks shared by the modules.

export function isString(value) {
  return typeof value === "string";
}

export function isNonEmptyString(value) {
  return isString(value) && value.trim() !== "";
}
