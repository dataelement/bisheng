import { parseHostInfo } from "./hostInfo";

const valid = {
  protocolVersion: 1,
  channel: "desktop",
  deviceType: "desktop",
  os: "windows",
};

describe("read-only host metadata", () => {
  it.each(["windows", "macos", "linux", "unknown"])("accepts v1 %s", (os) => {
    expect(parseHostInfo({ ...valid, os })).toEqual({ ...valid, os });
    expect(Object.isFrozen(parseHostInfo({ ...valid, os }))).toBe(true);
  });
  it.each([
    null,
    [],
    {},
    { ...valid, protocolVersion: 2 },
    { ...valid, channel: "web" },
    { ...valid, deviceType: "phone" },
  ])("ignores an invalid envelope %p", (value) => {
    expect(parseHostInfo(value)).toBeUndefined();
  });
  it.each([undefined, "win32", 123])(
    "keeps valid identity with unknown OS %p",
    (os) => {
      expect(parseHostInfo({ ...valid, os })?.os).toBe("unknown");
    },
  );
  it("ignores extra fields without mutating the host object", () => {
    const host = Object.freeze({ ...valid, extra: true });
    expect(parseHostInfo(host)).toEqual(valid);
    expect(host.extra).toBe(true);
  });
});

it("does not call malformed optional presentation methods", () => {
  const { readDesktopPresentation } =
    jest.requireActual<typeof import("./presentation")>("./presentation");
  window.dshChatPresentation = {
    reportLanding: "invalid",
    reportNavigation: "invalid",
  } as never;
  expect(readDesktopPresentation().reportLanding).toBeUndefined();
  expect(readDesktopPresentation().reportNavigation).toBeUndefined();
  delete window.dshChatPresentation;
});

it("ignores metadata with inaccessible properties", () => {
  expect(
    parseHostInfo({
      get protocolVersion() {
        throw new Error("blocked");
      },
    }),
  ).toBeUndefined();
});
