/** @jest-environment node */

import { shouldShowAiAccessSection, shouldShowPersonalTokenEntry } from "./personalTokenEntry";

describe("personal-token entry visibility", () => {
  it.each([
    [false, undefined, false],
    [false, false, false],
    [false, true, false],
    [true, undefined, false],
    [true, false, false],
    [true, true, true],
  ])(
    "uses deployment=%s and effective=%s to return %s",
    (deploymentEnabled, effectiveEnabled, expected) => {
      expect(shouldShowPersonalTokenEntry(deploymentEnabled, effectiveEnabled, true)).toBe(expected);
    },
  );
});

describe("AI-access UI gate", () => {
  it.each([undefined, false])("hides both entries when the UI switch is %s", (uiEnabled) => {
    expect(shouldShowPersonalTokenEntry(true, true, uiEnabled)).toBe(false);
    expect(shouldShowAiAccessSection(true, uiEnabled)).toBe(false);
  });
});

describe("ai-access settings section visibility", () => {
  it("requires the UI and deployment gates — tenant off keeps the explanation", () => {
    expect(shouldShowAiAccessSection(true, true)).toBe(true);
    expect(shouldShowAiAccessSection(false, true)).toBe(false);
  });
});
