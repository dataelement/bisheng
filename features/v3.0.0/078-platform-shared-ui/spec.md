# Platform shared UI — first migration batch

User-approved scope (2026-10-16): develop on `feat/3.0.0`, integrate
`@bisheng/ui`, and fully replace buttons, notices, and input fields. Old import
paths remain compatibility adapters, never an alternative visual implementation.
Other component families are outside this batch.

- AC-01: Platform compiles shared source and uses the existing semantic tokens
  and Tailwind preset. Shared component styles and design decisions stay unchanged.
- AC-02: Every legacy Button / LoadButton uses the shared Button. Loading blocks
  resubmission; refs, slots, variants, and numeric-stepper callbacks remain usable.
- AC-03: `message` uses shared Toast; legacy right-side `toast` uses shared
  Notification. Preserve severity, all description lines, update/dismiss handles,
  and localized close/expand labels, including calls from HTTP interceptors.
- AC-04: Input, search, password, textarea, nonnegative numeric fields, and list
  fields render shared input controls. Preserve refs, controlled/uncontrolled
  values, native length limits, numeric validation, and existing callback payloads.
- AC-05: No new UI libraries or duplicate component implementations. App-specific
  validation, labels, and translations belong in platform adapters.
- AC-06: Run component interaction tests, lint, typecheck, and a production build;
  record pre-existing failures and any unavailable browser verification honestly.
- AC-07: User approved platform-only theme mapping: retain the configured primary
  color through initial/late configuration loads and live edits; derive shared
  brand states for light/dark mode without changing shared component styles or
  functional colors. Removing the custom primary restores shared defaults.

Implementation: retain old entry points; adapt props and behavior at the boundary.
No backend changes. Shared components already have approved styles; migration is
not a redesign. Estimate and rollout approval are in the chat preceding this file.
