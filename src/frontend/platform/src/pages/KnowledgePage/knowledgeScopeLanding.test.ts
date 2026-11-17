import { expect, it } from "vitest";
import { knowledgeScopeLanding } from "./knowledgeScopeLanding";

it.each([
  ["/filelib/4391", "?parent_id=7&file_id=9&tab=settings", "/filelib"],
  ["/filelib/4391/settings", "?view=admin&parent_id=7", "/filelib?view=admin"],
  ["/filelib/upload/4391", "?view=admin&from=%2Ffilelib%2F4391", "/filelib?view=admin"],
  ["/filelib/create", "?tab=settings", "/filelib"],
  ["/filelib/4391", "?view=qa", "/filelib?view=qa"],
  ["/filelib/4391", "?view=admin&view=qa", "/filelib"],
  ["/filelib", "?view=admin", "/filelib?view=admin"],
  ["/filelib-extra/4391", "", null],
  ["/model", "?view=admin", null],
])("resolves %s%s to a tenant-neutral landing", (path, query, expected) => {
  expect(knowledgeScopeLanding(path, query)).toBe(expected);
});
