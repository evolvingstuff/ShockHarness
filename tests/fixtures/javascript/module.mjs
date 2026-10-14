export const LIMIT = 50;
export default function page(items) { return items.slice(0, LIMIT); }
