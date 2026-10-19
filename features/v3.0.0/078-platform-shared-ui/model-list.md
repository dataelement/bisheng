# Model management: provider list page

Approved on 2026-10-19: migrate by business page. Use finalized shared components;
retain missing or unfinalized families explicitly until design/library completion.
This slice covers `/model/management` in list mode. Provider configuration and
system-model configuration are separate page slices, not completed here.

## Acceptance criteria

- AC-ML-01: Provider expand/collapse, configuration entry, refresh and admin-scope
  switching remain available under the same permission rules.
- AC-ML-02: List actions, online switches, status/readonly tags and plain-text
  tooltips use finalized `@bisheng/ui` components without local visual overrides.
- AC-ML-03: Online changes lock only the affected model until the response;
  failure restores the persisted state and uses existing request error feedback.
  Status verification remains an explicit action and locks only its own button.
- AC-ML-04: Inherited readonly providers cannot be configured or toggled, while
  their status can still be inspected/verified as before.
- AC-ML-05: Table and admin-scope dropdown remain existing implementations.
  Select/cascader and ordinary dialogs in the configuration pages remain pending;
  they are not hidden behind a claim of complete shared-library replacement.

## Implementation / checks

- Extract typed `ModelProviderRow` and its model row. API coordination stays in
  the existing page; successful writes update by stable provider/model ids.
- Shared Switch owns loading appearance; page callers own request outcome.
- Scope trigger uses shared Button; menu content stays unchanged.
- Interaction tests cover expand/configure, pending/rejected toggle, independent
  status verification, inherited readonly state and empty providers.

## Page acceptance checklist

- [ ] Expand/collapse two providers and check empty providers.
- [ ] Verify model name, type, available/abnormal/unknown state and update time.
- [ ] Hover/focus the abnormal-status hint and inspect its full text.
- [ ] Update one model status; other models remain usable.
- [ ] Toggle a disposable model online/offline; no repeat request while loading.
- [ ] On failed online change, the control returns to its previous state.
- [ ] Open configuration and return; refresh the provider list.
- [ ] In multi-tenant mode, switch admin scope and verify inherited readonly rows.

No backend endpoint or shared component style changes. API E2E writes are not
run against shared test model services; the user performs live-page acceptance.

## Verification (2026-10-19)

- 21 interaction/permission tests passed (5 list scenarios and 16 existing
  permission cases); changed-source ESLint passed with shrink-only pruning.
- Platform strict typecheck passed (591 files); production build passed (34.65s).
- Independent read-only review found no actionable regression. Existing probe
  polling can still race a newer write response; this predates the migration.
- Isolated Chromium checks passed for pending-toggle lock/rejection rollback,
  independent verification buttons, keyboard tooltip and light/dark rendering.
  No JavaScript page errors. The headless browser blocked Vite HMR WebSockets;
  control interaction checks did not depend on HMR. Temporary fixtures removed.
- Browser screenshots: `model-list-light.png` / `model-list-dark.png` in the task's
  visualization directory. These are fixture checks, not authenticated API E2E.
- Manual page acceptance above remains pending. No real backend model writes.

User accepted the list refinements and requested the next unit on 2026-10-19.
The later module-level cadence in `module-plan.md` supersedes this file's separate
page acceptance checkpoint. Module 1 is delivered and tested as one whole unit.
