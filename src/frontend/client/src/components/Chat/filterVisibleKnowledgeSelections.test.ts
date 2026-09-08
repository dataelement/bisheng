/** @jest-environment node */

import { retainVisibleOrgKnowledgeSelections } from "./filterVisibleKnowledgeSelections";

describe("retainVisibleOrgKnowledgeSelections", () => {
  it("drops invisible organization knowledge bases and preserves spaces", () => {
    const selections = [
      { id: "12", name: "Hidden", type: "org" as const },
      { id: "13", name: "Visible", type: "org" as const },
      { id: "28", name: "Space", type: "space" as const },
    ];

    expect(retainVisibleOrgKnowledgeSelections(selections, [13])).toEqual([
      { id: "13", name: "Visible", type: "org" },
      { id: "28", name: "Space", type: "space" },
    ]);
  });

  it("preserves the array reference when every organization knowledge base is visible", () => {
    const selections = [{ id: "13", name: "Visible", type: "org" as const }];

    expect(retainVisibleOrgKnowledgeSelections(selections, ["13"])).toBe(selections);
  });
});
