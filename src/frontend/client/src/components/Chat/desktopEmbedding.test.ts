/** @jest-environment node */
import {
  getClientEnvironment,
  refreshClientEnvironment,
} from "~/utils/clientEnvironment";
import { isDesktopEmbedded } from "./desktopEmbedding";

it("provides a safe unknown identity without browser globals", () => {
  expect(isDesktopEmbedded()).toBe(false);
  expect(refreshClientEnvironment()).toBe(getClientEnvironment());
  expect(getClientEnvironment()).toMatchObject({
    channel: "web",
    deviceType: "unknown",
    os: "unknown",
  });
});
