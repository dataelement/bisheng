import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Button, Select } from "@bisheng/ui";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { LoadingState } from "./LoadingState";
import { PlatformLoadingProvider } from "./PlatformLoadingProvider";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const originalBrand = window.BRAND_CONFIG;
afterEach(() => {
  cleanup();
  window.BRAND_CONFIG = originalBrand;
});

it("uses the configured loading asset without visible loading text", () => {
  window.BRAND_CONFIG = {
    ...originalBrand,
    URLLoadingIcon: "https://assets.test/custom-loading.svg",
    loadingAnimation: "animate-pulse",
  };
  render(<LoadingState size="page" label="loading-documents" />);
  const status = screen.getByRole("status", { name: "loading-documents" });
  expect(status).toHaveAttribute("aria-busy", "true");
  expect(status).toHaveTextContent("");
  const asset = status.querySelector("img");
  expect(asset).toHaveAttribute("src", "https://assets.test/custom-loading.svg");
  expect(asset).toHaveClass("size-20", "max-w-none", "animate-pulse");
});

function PlatformSelect() {
  return <Select {...useSelectLabels()} options={[]} loading open aria-label="models" />;
}

it("uses a single configured indicator inside platform select panels", () => {
  window.BRAND_CONFIG = { ...originalBrand, URLLoadingIcon: "https://assets.test/select-loading.svg" };
  render(<PlatformLoadingProvider><PlatformSelect /></PlatformLoadingProvider>);
  const status = screen.getByRole("status", { name: "sharedUi.selectLoading" });
  expect(status.querySelector("img")).toHaveAttribute("src", "https://assets.test/select-loading.svg");
  expect(status.parentElement?.querySelectorAll("svg")).toHaveLength(0);
  expect(screen.queryByText("sharedUi.selectLoading")).toBeNull();
});

it("preserves the default select loading presentation for other consumers", () => {
  render(<Select options={[]} loading open loadingText="client-loading" aria-label="models" />);
  expect(screen.getByText("client-loading")).toBeVisible();
  expect(screen.getByRole("status").querySelector("svg")).not.toBeNull();
});

it("applies the platform asset to built-in button and select loading", () => {
  window.BRAND_CONFIG = { ...originalBrand, URLLoadingIcon: "https://assets.test/platform-loading.svg" };
  render(
    <PlatformLoadingProvider>
      <Button loading>save</Button>
      <Select options={[]} loading open loadingText="loading-options" aria-label="models" />
    </PlatformLoadingProvider>,
  );
  expect(screen.getByRole("button", { name: "save" }).querySelector("img")).toHaveAttribute("src", "https://assets.test/platform-loading.svg");
  const status = screen.getByRole("status", { name: "loading-options" });
  expect(status.querySelector("img")).toHaveAttribute("src", "https://assets.test/platform-loading.svg");
  expect(status.querySelector("svg")).toBeNull();
  expect(screen.queryByText("loading-options")).toBeNull();
});
