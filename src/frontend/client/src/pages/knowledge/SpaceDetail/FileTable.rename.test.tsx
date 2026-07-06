import { readFileSync } from "fs";
import { join } from "path";

function read(rel: string): string {
  return readFileSync(join(__dirname, rel), "utf8");
}

describe("FileTable rename input — read-only extension", () => {
  const src = read("FileTable.tsx");

  it("destructures ext from useInlineRename", () => {
    expect(src).toMatch(/ext,/);
  });

  it("renders the extension as a read-only suffix next to the rename input", () => {
    // ext is shown only when non-empty, via a dedicated suffix span
    expect(src).toMatch(/ext\s*&&/);
    expect(src).toMatch(/data-testid="rename-ext-suffix"/);
  });
});
