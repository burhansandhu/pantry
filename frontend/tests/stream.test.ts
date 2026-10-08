import test from "node:test";
import assert from "node:assert/strict";
import { readEvents } from "../lib/stream.ts";

function response(parts: Uint8Array[]) {
  return new Response(new ReadableStream({start(controller) {parts.forEach(p => controller.enqueue(p)); controller.close();}}));
}

test("SSE survives byte splits, unicode, CRLF and incremental tokens", async () => {
  const wire = 'data: {"type":"token","text":"café 🍲"}\r\n\r\ndata: {"type":"token","text":" next"}\n\ndata: {"type":"done","recipe":"café 🍲 next"}\n\n';
  const bytes = new TextEncoder().encode(wire);
  const received: Record<string, unknown>[] = [];
  await readEvents(response(Array.from(bytes, b => new Uint8Array([b]))), event => received.push(event));
  assert.equal(received.length, 3);
  assert.equal(received[0].text, "café 🍲");
  assert.equal(received[1].text, " next");
});

test("A broken stream produces an actionable error", async () => {
  await assert.rejects(readEvents(response([new TextEncoder().encode('data: {"type":"token","text":"partial"}\n\n')]), () => {}), /connection ended/);
});

test("HTTP validation errors are readable", async () => {
  await assert.rejects(readEvents(new Response(JSON.stringify({detail:[{msg:"Please enter an ingredient"}]}), {status:422}), () => {}), /Please enter an ingredient/);
});
