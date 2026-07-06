import { readFileSync } from "fs";
import { join } from "path";

const src = readFileSync(join(__dirname, "CreateKnowledgeSpaceDrawer.tsx"), "utf8");

describe("CreateKnowledgeSpaceDrawer — personal level disabled", () => {
  it("disables the PERSONAL level option for creation", () => {
    // PERSONAL 选项 enabled 恒为 false（禁止手动新建个人库）
    const personalBlock = src.slice(src.indexOf("SpaceLevel.PERSONAL,"));
    expect(personalBlock).toMatch(/enabled:\s*false/);
  });
});
