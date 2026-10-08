/** Parse pasted lists without splitting commas inside an ingredient's notes. */
export function splitItems(text: string): string[] {
  const items: string[] = [];
  let item = "";
  let depth = 0;
  let quoted = false;
  function push() {
    const clean = item.trim().replace(/^(?:[•‣●*\-]|\d+[.)])\s+/, "").trim();
    if (clean) items.push(clean);
    item = "";
  }
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (char === '"') {
      if (quoted && text[i + 1] === '"') { item += '"'; i++; }
      else quoted = !quoted;
    } else if (!quoted && (char === "\n" || char === "\r" || ((char === "," || char === ";") && depth === 0))) {
      push();
      if (char === "\n" || char === "\r") depth = 0;
    } else {
      if (!quoted && "([{".includes(char)) depth++;
      if (!quoted && ")]}".includes(char)) depth = Math.max(0, depth - 1);
      item += char;
    }
  }
  push();
  return [...new Set(items)];
}
