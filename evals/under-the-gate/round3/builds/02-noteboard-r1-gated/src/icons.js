// Inline SVG icons for the note toolbar (24x24 outline icons).

const SVG_NS = "http://www.w3.org/2000/svg";

const ICON_PATHS = Object.freeze({
  pin: "M9 4h6l-1 6 3 3v2H7v-2l3-3-1-6zM12 15v5",
  delete: "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6",
});

export function createIcon(doc, name) {
  if (!Object.hasOwn(ICON_PATHS, name)) {
    throw new Error(`no icon named ${JSON.stringify(name)}`);
  }
  const svg = doc.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  svg.classList.add("icon");
  const path = doc.createElementNS(SVG_NS, "path");
  path.setAttribute("d", ICON_PATHS[name]);
  svg.append(path);
  return svg;
}
