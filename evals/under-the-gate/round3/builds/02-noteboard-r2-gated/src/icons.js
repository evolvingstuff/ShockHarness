// Inline SVG icons for the note toolbar.

const SVG_NS = "http://www.w3.org/2000/svg";

const PATHS = Object.freeze({
  pin: "M16 3l5 5-3 1-4 4 1 5-2 2-4-4-5 5-1-1 5-5-4-4 2-2 5 1 4-4z",
  delete: "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6",
});

export function icon(doc, name) {
  const svg = doc.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("class", "icon");
  const path = doc.createElementNS(SVG_NS, "path");
  path.setAttribute("d", PATHS[name]);
  svg.append(path);
  return svg;
}
