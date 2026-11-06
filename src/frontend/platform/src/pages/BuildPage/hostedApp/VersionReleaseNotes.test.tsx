import { fireEvent, render, screen, within } from "@testing-library/react"
import { expect, it } from "vitest"
import { VersionReleaseNotes } from "./VersionReleaseNotes"

it("shows a fixed action label and reads full notes in a centered modal", () => {
  render(<VersionReleaseNotes notes={"First\nSecond\nThird\nFourth"} />)
  expect(screen.queryByText(/First/)).toBeNull()
  fireEvent.click(screen.getByRole("button", { name: "hostedApp.releaseNotes.column" }))
  const dialog = screen.getByRole("dialog", { name: "hostedApp.releaseNotes.column" })
  expect(dialog).toHaveAttribute("aria-modal", "true")
  expect(dialog).toHaveClass("top-[50%]", "left-[50%]")
  expect(dialog).toHaveTextContent("First Second Third Fourth")
  fireEvent.click(within(dialog).getByRole("button", { name: "Close" }))
  expect(screen.queryByRole("dialog")).toBeNull()
})

it("shows the empty state in the modal for versions without notes", () => {
  render(<VersionReleaseNotes />)
  fireEvent.click(screen.getByRole("button", { name: "hostedApp.releaseNotes.column" }))
  expect(screen.getByRole("dialog")).toHaveTextContent("hostedApp.releaseNotes.empty")
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" })
  expect(screen.queryByRole("dialog")).toBeNull()
})
