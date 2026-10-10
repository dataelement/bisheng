/** @jest-environment node */

import { shouldShowPersonalTokenEntry } from "./personalTokenEntry";

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
      expect(shouldShowPersonalTokenEntry(deploymentEnabled, effectiveEnabled)).toBe(expected);
    },
  );
});

describe("ai-access settings section visibility", () => {
  it("follows the deployment gate only — tenant off keeps the section for its explanation", async () => {
    const { shouldShowAiAccessSection } = await import("./personalTokenEntry");
    expect(shouldShowAiAccessSection(true)).toBe(true);
    expect(shouldShowAiAccessSection(false)).toBe(false);
  });
});
