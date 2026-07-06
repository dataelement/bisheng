import { readFileSync } from "fs";
import { join } from "path";

function read(rel: string): string {
  return readFileSync(join(__dirname, rel), "utf8");
}

describe("FileCard rename input — read-only extension", () => {
  const src = read("FileCard.tsx");

  it("destructures ext from useInlineRename", () => {
    expect(src).toMatch(/ext,/);
  });

  it("renders the extension as a read-only suffix next to the rename input", () => {
    expect(src).toMatch(/ext\s*&&/);
    expect(src).toMatch(/data-testid="rename-ext-suffix"/);
  });
});
