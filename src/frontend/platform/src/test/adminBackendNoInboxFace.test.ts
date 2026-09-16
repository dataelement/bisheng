/**
 * F056 T033 / AC-39 — the admin backend has no message face.
 *
 * Every station message in §3.0.3 is received in one place: the client
 * workbench's 「消息提醒」 bell. That includes the messages whose recipients are
 * tenant administrators and approvers — people who spend their day in this
 * app. The temptation to "also show it here, they are already looking at the
 * admin pages" is exactly what the AC rules out, and the failure mode is a
 * split inbox where a message read in one place still shows unread in the
 * other.
 *
 * Asserted as a census over the endpoints rather than over components: a second
 * inbox needs the inbox endpoints, whatever it looks like. The whole `src`
 * tree is scanned, not only `controllers/` — the rule that HTTP lives in the
 * API layer is a convention, and a second inbox is exactly the kind of change
 * that would be prototyped with a call straight from a component.
 */
import { readdirSync, readFileSync, statSync } from "node:fs"
import { join, resolve } from "node:path"
import { describe, expect, it } from "vitest"

/** The client's inbox endpoints (`client/src/api/message.ts`). */
const INBOX_ENDPOINTS = [
  "/api/v1/message/list",
  "/api/v1/message/unread_count",
  "/api/v1/message/mark_read",
  "/api/v1/message/mark_all_read",
  "/api/v1/message/approve",
]

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) return sourceFiles(full)
    return /\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry) ? [full] : []
  })
}

const SRC_ROOT = resolve(__dirname, "..")

describe("the admin app never calls the inbox", () => {
  // `test/` is this file's own home — the endpoint strings above would
  // otherwise report themselves.
  const files = sourceFiles(SRC_ROOT).filter((file) => !file.startsWith(join(SRC_ROOT, "test")))

  it.each(INBOX_ENDPOINTS)("nothing in the app requests %s", (endpoint) => {
    const offenders = files
      .filter((file) => readFileSync(file, "utf-8").includes(endpoint))
      .map((file) => file.slice(SRC_ROOT.length + 1))
    expect(offenders).toEqual([])
  })

  it("scans the API layer and the pages, not an empty set", () => {
    // Guards the guard: a path typo would make every assertion above pass over
    // zero files. Both roots are named because the whole point of widening the
    // scan past `controllers/` is that a component could call the inbox
    // directly.
    expect(files.filter((file) => file.startsWith(join(SRC_ROOT, "controllers"))).length).toBeGreaterThan(5)
    expect(files.filter((file) => file.startsWith(join(SRC_ROOT, "pages"))).length).toBeGreaterThan(5)
  })
})
