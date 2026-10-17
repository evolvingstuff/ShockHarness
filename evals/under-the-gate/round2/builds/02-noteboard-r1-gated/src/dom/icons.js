// Inline SVG icons for the note toolbar.

const SVG_NS = "http://www.w3.org/2000/svg";

const ICON_PATHS = Object.freeze({
  pin: "M16 3l5 5-3 1-4 4 1 5-2 2-4-4-5 5-1-1 5-5-4-4 2-2 5 1 4-4z",
  delete: "M9 3h6l1 2h4v2H4V5h4zm-3 6h12l-1 12H7z",
});

export function createIcon(name) {
  if (!Object.hasOwn(ICON_PATHS, name)) {
    throw new RangeError(`unknown icon ${name}`);
  }
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  svg.classList.add("icon");
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", ICON_PATHS[name]);
  svg.append(path);
  return svg;
}
