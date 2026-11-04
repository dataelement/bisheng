/** @jest-environment node */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const html = readFileSync(resolve(__dirname, "../../../index.html"), "utf8");
const script = html
  .split("<script>")
  .map((value) => value.split("</script>")[0])
  .find((value) => value.includes("Paint the native host theme"));
if (!script) throw new Error("Missing host theme bootstrap");

function paint(
  search: string,
  values: Record<string, string> = {},
  presentation?: unknown,
  blocked = false,
) {
  const root = { dataset: {} as Record<string, string> };
  const storage = {
    getItem: (key: string) => {
      if (blocked) throw new Error("blocked");
      return values[key];
    },
  };
  new Function(
    "window",
    "document",
    "location",
    "sessionStorage",
    "matchMedia",
    script as string,
  )(
    { dshChatPresentation: presentation },
    { documentElement: root },
    { search },
    storage,
    undefined,
  );
  return root.dataset.dshHostTheme;
}

it("uses the same theme key and values after query-free refresh", () => {
  expect(
    paint("", { "dsh:embedded-chat": "true", "dsh:host-theme": "dark" }),
  ).toBe("dark");
  expect(paint("?embed=dsh&dshTheme=light", { "dsh:host-theme": "dark" })).toBe(
    "light",
  );
});
it("paints v1 and legacy preloads without storage or matchMedia", () => {
  const host = {
    hostInfo: {
      protocolVersion: 1,
      channel: "desktop",
      deviceType: "desktop",
      os: "macos",
    },
  };
  expect(paint("?dshTheme=dark", {}, host, true)).toBe("dark");
  expect(paint("", {}, { reportLanding: () => {} }, true)).toBe("light");
});
it("ignores invalid metadata and web-only theme-looking parameters", () => {
  expect(paint("?dshTheme=dark")).toBeUndefined();
  expect(
    paint(
      "",
      {},
      {
        hostInfo: {
          protocolVersion: 2,
          channel: "desktop",
          deviceType: "desktop",
        },
      },
    ),
  ).toBeUndefined();
});
