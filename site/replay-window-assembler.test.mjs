import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";

globalThis.window = {};
const source = await fs.readFile(new URL("./replay-window-assembler.js", import.meta.url), "utf8");
await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const Assembler = window.FutureViewDisplayWindowAssembler;

test("single display window passes through immediately", () => {
  const assembler = new Assembler();
  assert.deepEqual(
    assembler.accept({ bars: [{ t: 1 }, { t: 2 }] }),
    { complete: true, bars: [{ t: 1 }, { t: 2 }] },
  );
});

test("chunked windows assemble once all chunks arrive", () => {
  const assembler = new Assembler();
  assert.deepEqual(
    assembler.accept({ transfer_id: "a", chunk_index: 1, chunk_count: 3, bars: [{ t: 3 }] }),
    { complete: false, bars: null },
  );
  assert.deepEqual(
    assembler.accept({ transfer_id: "a", chunk_index: 0, chunk_count: 3, bars: [{ t: 1 }, { t: 2 }] }),
    { complete: false, bars: null },
  );
  assert.deepEqual(
    assembler.accept({ transfer_id: "a", chunk_index: 2, chunk_count: 3, bars: [{ t: 4 }] }),
    { complete: true, bars: [{ t: 1 }, { t: 2 }, { t: 3 }, { t: 4 }] },
  );
});

test("reset discards an incomplete transfer", () => {
  const assembler = new Assembler();
  assembler.accept({ transfer_id: "a", chunk_index: 0, chunk_count: 2, bars: [{ t: 1 }] });
  assembler.reset();
  assert.deepEqual(
    assembler.accept({ transfer_id: "a", chunk_index: 1, chunk_count: 2, bars: [{ t: 2 }] }),
    { complete: false, bars: null },
  );
});
