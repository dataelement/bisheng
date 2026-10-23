# Remaining shared primitive cleanup

**Goal:** Remove legacy implementations of Textarea, Switch, Checkbox, Radio,
Badge/Tag, Tooltip, Tabs and Breadcrumb from client and platform; callers import
shared primitives directly. This continues the approved shared UI migration.

**Architecture:** Preserve business state, navigation, selection, refs and form
validation at call sites. Use shared controls without introducing compatibility
wrappers. Status labels use Tag; numeric/unread indicators use Badge. Shared
visual decisions stay owned by the design system.

**Tech stack:** TypeScript, React, @bisheng/ui; each app keeps its existing stores,
request layer and localization.

**Spec:** spec.md; user-approved continuation covering the nine remaining families.

## Constraints

- Work on feat/3.0.0; keep unrelated changes.
- Do not invent components, edit design specs or add UI libraries.
- Preserve form limits and selection behavior; stop for product decisions.
- Delete old implementations only after checking all callers and barrel exports.
- No test checklist documents; verification evidence stays in command logs.

## Tasks

- [x] Migrate Switch, Checkbox and Radio imports/props, then remove old files.
- [x] Migrate Textarea with shell/field classes and explicit submission limits.
- [x] Migrate status labels/closable tags and actual count badges by semantics.
- [x] Migrate tooltip triggers/content and tab/panel composition at business sites.
- [x] Remove the unused breadcrumb primitive and orphan dashboard header; current routes are unchanged.
- [x] Check remaining imports, focused behavioral tests, lint, types and builds.

## Review focus

Indeterminate selection; disabled controls; keyboard/focus and ref behavior;
soft length limits at submit; controlled tabs and hidden-panel lifecycle;
rich tooltip content that may require a product decision; existing navigation.

## Decisions and boundaries

Both client and platform now consume these basic primitives directly. Nineteen
legacy files were removed, including the old tooltip/toggle adapters. Source
imports and barrel exports no longer reference the removed entry points.

- Status/source labels use Tag; selected options use its close action; actual
  numeric indicators use Badge. Clickable source actions use Button.
- Rich hover content (channel/knowledge metadata, notification user card,
  image guide, guest application details) retains its content and hover/focus
  interaction through the existing HoverCard, as approved by the user.
- Preview/code mode uses Segmented; speech settings and inline authentication
  radios use shared controls. The vertical settings navigation remains on its
  existing implementation because the shared library only has horizontal tabs.
- The old /d/prompts dashboard route is not registered by the current router.
  Its orphan breadcrumb header was removed; no active navigation was changed.
- TextareaAutosize remains an application-specific direction/autosizing
  composition over react-textarea-autosize; it is not a duplicated visual skin.
  Embedded Sandpack component source strings also remain isolated from app UI.
- SelectTrigger's existing asChild mode now supplies exactly one child; selected
  tags can have native close buttons without nesting buttons. Disabled selections
  remain immutable, and a menu popover receives trigger events through the DOM.

## Verification evidence

Focused client tests cover comment limits/correction, reopen reset, locked and
disabled selections, permission dialogs, native select behavior and preset
opening by pointer/keyboard. The legacy preset composition was observed failing
before the corrected composition passed. Independent review also checked refs,
input height limits and hover-card keyboard access.

Scoped lint has no errors, localization parity passes with a smaller legacy
baseline, and production builds pass for both applications. Platform types pass;
client typechecking retains the same four unrelated skill-center errors in
api/skillCenter.ts and components/Skills/useSkillCenter.ts. Full-app lint still
reports legacy errors outside the changed files. No suppressions were added;
obsolete entries were pruned with the lint tooling. No commit or push requested.

Final acceptance run: 237 platform tests in 46 files and 14 client tests in 3 files pass. Both production builds pass; direct old-entry import/export scan finds zero references. Full lint/type baseline limitations are recorded above.
