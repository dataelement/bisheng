import { VersionDiffView, classifyDiffLine } from "@bisheng/file-viewers"
import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

/**
 * The cross-app diff presentation (F055 AC-41 / T064). It lives in
 * `@bisheng/file-viewers` because the platform's version tab and the client's
 * review view must render the *same* component, and the two SPAs share no
 * `src/`. It is exercised from here because platform's vitest setup mocks
 * `react-i18next` to echo keys back, which makes the assertions read as the
 * component's copy contract.
 *
 * `useTranslation('shared', { keyPrefix: 'hostedApp.versionDiff' })` under
 * that mock yields the bare key, so `identical` below is the real key
 * `hostedApp.versionDiff.identical` at runtime.
 */

const FILES = [
  { path: "main.py", change: "modified", additions: 3, deletions: 1, comparable: true, reason: null },
  { path: "assets/logo.png", change: "added", additions: 0, deletions: 0, comparable: false, reason: "binary" },
  { path: "old.py", change: "removed", additions: 0, deletions: 9, comparable: true, reason: null },
]

const PATCHES = [
  {
    path: "main.py",
    change: "modified",
    patch: "--- a/main.py\n+++ b/main.py\n@@ -1,2 +1,2 @@\n-old = 1\n+new = 1\n unchanged\n",
    truncated: false,
    masked_secrets: 2,
  },
  { path: "old.py", change: "removed", patch: null, truncated: true, masked_secrets: 0 },
]

const SUMMARY = { files_changed: 3, additions: 3, deletions: 10, truncated: false }

describe("VersionDiffView", () => {
  it("test_classify_diff_line_treats_headers_as_meta_not_add_or_delete", () => {
    expect(classifyDiffLine("+++ b/main.py")).toBe("meta")
    expect(classifyDiffLine("--- a/main.py")).toBe("meta")
    expect(classifyDiffLine("@@ -1,2 +1,2 @@")).toBe("hunk")
    expect(classifyDiffLine("+new = 1")).toBe("add")
    expect(classifyDiffLine("-old = 1")).toBe("del")
    expect(classifyDiffLine(" unchanged")).toBe("context")
  })

  it("test_lists_every_changed_file_and_opens_the_first_one", () => {
    render(<VersionDiffView summary={SUMMARY} files={FILES} patches={PATCHES} />)

    expect(screen.getByTestId("version-diff-view")).toBeInTheDocument()
    expect(screen.getByText("filesChanged")).toBeInTheDocument()
    for (const file of FILES) {
      expect(screen.getAllByTitle(file.path).length).toBeGreaterThan(0)
    }
    // The first file is selected on mount, so its patch body is already on screen.
    expect(screen.getByText("+new = 1")).toBeInTheDocument()
    expect(screen.getByText("-old = 1")).toBeInTheDocument()
    expect(screen.getByText("maskedSecrets")).toBeInTheDocument()
  })

  it("test_binary_file_is_listed_but_degraded_to_a_reason_instead_of_a_patch", () => {
    render(<VersionDiffView summary={SUMMARY} files={FILES} patches={PATCHES} />)

    fireEvent.click(screen.getByRole("button", { name: /assets\/logo\.png/ }))

    expect(screen.getByText("reasonBinary")).toBeInTheDocument()
    expect(screen.queryByText("+new = 1")).not.toBeInTheDocument()
  })

  it("test_file_dropped_by_the_total_size_cap_says_so_instead_of_rendering_empty", () => {
    render(<VersionDiffView summary={SUMMARY} files={FILES} patches={PATCHES} />)

    fireEvent.click(screen.getByRole("button", { name: /old\.py/ }))

    expect(screen.getByText("patchOmitted")).toBeInTheDocument()
  })

  it("test_identical_versions_say_so_rather_than_showing_an_empty_frame", () => {
    render(
      <VersionDiffView
        summary={{ files_changed: 0, additions: 0, deletions: 0, truncated: false }}
        files={[]}
        patches={[]}
      />,
    )
    expect(screen.getByText("identical")).toBeInTheDocument()
  })

  it("test_loading_error_and_empty_each_replace_the_list", () => {
    const { rerender } = render(<VersionDiffView summary={null} files={FILES} patches={PATCHES} loading />)
    expect(screen.getByText("loading")).toBeInTheDocument()
    expect(screen.queryByTestId("version-diff-view")).not.toBeInTheDocument()

    rerender(<VersionDiffView summary={null} files={FILES} patches={PATCHES} errorMessage="no permission" />)
    expect(screen.getByText("no permission")).toBeInTheDocument()

    rerender(<VersionDiffView summary={null} files={FILES} patches={PATCHES} emptyMessage="first release" />)
    expect(screen.getByText("first release")).toBeInTheDocument()
  })

  it("test_selection_follows_a_new_file_list_instead_of_going_blank", () => {
    const { rerender } = render(<VersionDiffView summary={SUMMARY} files={FILES} patches={PATCHES} />)
    fireEvent.click(screen.getByRole("button", { name: /old\.py/ }))
    expect(screen.getByText("patchOmitted")).toBeInTheDocument()

    // Another pair of versions picked: the previous selection is gone from the
    // list, and the pane must land on the new first file, not on nothing.
    const nextFiles = [
      { path: "other.py", change: "added", additions: 1, deletions: 0, comparable: true, reason: null },
    ]
    const nextPatches = [
      {
        path: "other.py",
        change: "added",
        patch: "--- /dev/null\n+++ b/other.py\n@@ -0,0 +1 @@\n+fresh = 1\n",
        truncated: false,
        masked_secrets: 0,
      },
    ]
    rerender(<VersionDiffView summary={SUMMARY} files={nextFiles} patches={nextPatches} />)

    expect(screen.getByText("+fresh = 1")).toBeInTheDocument()
    expect(screen.queryByText("patchOmitted")).not.toBeInTheDocument()
  })
})
