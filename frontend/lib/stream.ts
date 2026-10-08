/** Decode complete SSE frames, including UTF-8 or frames split across reads. */
export async function readEvents(response: Response, onEvent: (value: Record<string, unknown>) => void) {
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = payload.detail;
    throw new Error(typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d: { msg: string }) => d.msg).join(" ") : "The kitchen could not process your request.");
  }
  if (!response.body) throw new Error("Streaming is unavailable in this browser.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  let finished = false;
  function consume() {
    let boundary;
    while ((boundary = /\r?\n\r?\n/.exec(pending))) {
      const frame = pending.slice(0, boundary.index);
      pending = pending.slice(boundary.index + boundary[0].length);
      const data = frame.split(/\r?\n/).filter(line => line.startsWith("data:")).map(line => line.slice(5).trimStart()).join("\n");
      if (data) {
        const event = JSON.parse(data);
        if (["review", "done", "error"].includes(event.type)) finished = true;
        onEvent(event);
      }
    }
  }
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      pending += decoder.decode(value, { stream: true });
      consume();
    }
    pending += decoder.decode();
    consume();
    if (!finished) throw new Error("The connection ended before the step finished. Start a new recipe to retry.");
  } finally {
    reader.releaseLock();
  }
}
