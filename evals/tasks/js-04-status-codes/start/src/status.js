// HTTP status handling (starting point: bare protocol literals).

export function isOk(status) {
  return status === 200;
}

export function isMissing(status) {
  return status === 404;
}

export function isServerError(status) {
  return status >= 500;
}
