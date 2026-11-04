import type { ClientEnvironment } from "./types";

type EnvironmentModule = typeof import("./index");
let env: EnvironmentModule;
const storageDescriptor = Object.getOwnPropertyDescriptor(
  window,
  "sessionStorage",
);

function load(search = "") {
  window.history.replaceState({}, "", `/${search}`);
  jest.isolateModules(() => {
    env = jest.requireActual<EnvironmentModule>("./index");
  });
  return env.getClientEnvironment();
}

beforeEach(() => {
  if (storageDescriptor)
    Object.defineProperty(window, "sessionStorage", storageDescriptor);
  window.sessionStorage.clear();
  delete window.dshChatPresentation;
  delete document.documentElement.dataset.bishengSurface;
});
afterEach(() => {
  if (storageDescriptor)
    Object.defineProperty(window, "sessionStorage", storageDescriptor);
});

it("keeps Web identity and stable snapshots without desktop signals", () => {
  const initial = load();
  expect(initial.channel).toBe("web");
  expect(env.getClientEnvironment()).toBe(initial);
  expect(env.refreshClientEnvironment()).toBe(initial);
  expect(document.documentElement.dataset.bishengSurface).toBe("web");
  expect(Object.isFrozen(initial.sources)).toBe(true);
});

it.each(["getter", "read", "write"])(
  "remembers an entry after route removal with blocked storage %s",
  (failure) => {
    const fail = () => {
      throw new Error("blocked");
    };
    if (failure === "getter")
      Object.defineProperty(window, "sessionStorage", {
        configurable: true,
        get: fail,
      });
    else
      jest
        .spyOn(Storage.prototype, failure === "read" ? "getItem" : "setItem")
        .mockImplementation(fail);
    load("?embed=dsh");
    window.history.replaceState({}, "", "/knowledge");
    expect(env.refreshClientEnvironment().channel).toBe("desktop");
    expect(document.documentElement.dataset.bishengSurface).toBe("desktop");
  },
);

it("publishes a new desktop entry once and keeps DOM and subscribers consistent", () => {
  load();
  const received: ClientEnvironment[] = [];
  const unsubscribe = env.subscribeClientEnvironment(() =>
    received.push(env.getClientEnvironment()),
  );
  window.history.replaceState({}, "", "/?embed=dsh");
  env.refreshClientEnvironment();
  env.refreshClientEnvironment();
  expect(received).toHaveLength(1);
  expect(received[0].channel).toBe(
    document.documentElement.dataset.bishengSurface,
  );
  unsubscribe();
});

it("restores a tab entry on a simulated module reload, but does not guess a host OS", () => {
  load("?embed=dsh");
  expect(load()).toMatchObject({
    channel: "desktop",
    os: "unknown",
    sources: { channel: "session" },
  });
});

it("accepts a read-only v1 without URL/session and reports actual method capability separately", () => {
  window.dshChatPresentation = Object.freeze({
    hostInfo: Object.freeze({
      protocolVersion: 1,
      channel: "desktop",
      deviceType: "desktop",
      os: "macos",
    }),
  });
  expect(load()).toMatchObject({
    channel: "desktop",
    deviceType: "desktop",
    os: "macos",
    capabilities: { hasNativePresentation: false },
    sources: { os: "host" },
  });
});

it("recognizes a legacy bridge after reload and safely ignores invalid metadata", () => {
  window.dshChatPresentation = {
    reportLanding: jest.fn(),
    hostInfo: { protocolVersion: 2 },
  };
  expect(load()).toMatchObject({
    channel: "desktop",
    os: "unknown",
    sources: { channel: "legacy-bridge" },
    capabilities: { hasNativePresentation: true },
  });
});

it("uses generic web when every durable signal was lost", () => {
  Object.defineProperty(window, "sessionStorage", {
    configurable: true,
    get: () => {
      throw new Error("blocked");
    },
  });
  expect(load()).toMatchObject({ channel: "web" });
});
