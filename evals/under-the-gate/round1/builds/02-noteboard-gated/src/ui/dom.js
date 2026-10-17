const SVG_NS = "http://www.w3.org/2000/svg";

export function el(doc, tag, attrs, children) {
  const node = doc.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
  node.append(...children);
  return node;
}

export function iconButton(doc, action, label, pathData) {
  const svg = doc.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("aria-hidden", "true");
  const path = doc.createElementNS(SVG_NS, "path");
  path.setAttribute("d", pathData);
  svg.append(path);
  return el(doc, "button", { type: "button", "data-action": action, "aria-label": label, title: label }, [svg]);
}
