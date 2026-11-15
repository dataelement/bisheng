import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { ClientEnvironmentSync } from "./ClientEnvironmentSync";
import { useClientEnvironment } from "~/hooks/useClientEnvironment";

function Probe() {
  const navigate = useNavigate();
  const env = useClientEnvironment();
  return (
    <>
      <ClientEnvironmentSync />
      <output>{env.channel}</output>
      <button
        onClick={() => {
          window.history.replaceState({}, "", "/?embed=dsh");
          navigate("/knowledge?embed=dsh");
        }}
      >
        embed
      </button>
      <button
        onClick={() => {
          window.history.replaceState({}, "", "/knowledge");
          navigate("/knowledge");
        }}
      >
        clean
      </button>
    </>
  );
}

it("updates subscribers and surface on explicit route entry and query removal", () => {
  render(
    <MemoryRouter>
      <Probe />
    </MemoryRouter>,
  );
  expect(screen.getByText("web")).toBeInTheDocument();
  fireEvent.click(screen.getByText("embed"));
  expect(screen.getByText("desktop")).toBeInTheDocument();
  fireEvent.click(screen.getByText("clean"));
  expect(screen.getByText("desktop")).toBeInTheDocument();
  expect(document.documentElement.dataset.bishengSurface).toBe("desktop");
});
