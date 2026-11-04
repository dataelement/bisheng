import { readBrowserIdentity } from "./browserIdentity";

const cases = [
  [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15 Safari/604",
    "phone",
    "ios",
  ],
  [
    "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) Mobile/15 Safari/604",
    "tablet",
    "ios",
  ],
  [
    "Mozilla/5.0 (Linux; Android 13; Pixel) AppleWebKit/537 Chrome/120 Mobile Safari/537",
    "phone",
    "android",
  ],
  [
    "Mozilla/5.0 (Linux; Android 13; SM-X) AppleWebKit/537 Chrome/120 Safari/537",
    "tablet",
    "android",
  ],
  [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537 Chrome/120 Safari/537",
    "desktop",
    "windows",
  ],
  [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605 Safari/605",
    "desktop",
    "macos",
  ],
  [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537 Chrome/120 Safari/537",
    "desktop",
    "linux",
  ],
  ["Android TV Chrome/120 Safari/537", "unknown", "android"],
  ["Android wearable", "unknown", "android"],
  ["Android", "unknown", "android"],
  ["unknown", "unknown", "unknown"],
  ["iPhone Android Mobile Safari/604", "unknown", "unknown"],
] as const;

describe("bounded browser identity inference", () => {
  it.each(cases)("%s → %s/%s", (userAgent, deviceType, os) => {
    expect(readBrowserIdentity({ userAgent })).toMatchObject({
      deviceType,
      os,
    });
  });
  it("does not claim a Macintosh with multiple touch points is a Mac or iPad", () => {
    expect(
      readBrowserIdentity({ userAgent: cases[5][0], maxTouchPoints: 5 }),
    ).toMatchObject({ deviceType: "unknown", os: "unknown" });
  });
  it("does not infer devices from platform, touch or UAData.mobile alone", () => {
    expect(
      readBrowserIdentity({
        userAgent: "",
        maxTouchPoints: 10,
        platform: "Windows",
      }),
    ).toMatchObject({
      deviceType: "unknown",
      os: "windows",
      osSource: "client-hints",
    });
  });
  it("rejects conflicting platform signals", () => {
    expect(
      readBrowserIdentity({ userAgent: cases[4][0], platform: "macOS" }).os,
    ).toBe("unknown");
  });
});
