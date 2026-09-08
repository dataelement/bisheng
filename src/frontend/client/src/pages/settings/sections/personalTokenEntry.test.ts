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
