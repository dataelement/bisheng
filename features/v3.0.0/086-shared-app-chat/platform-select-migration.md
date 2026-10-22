# Platform Select migration follow-up

2026-10-22. User authorized replacing remaining platform Select controls and
explicitly keeping specialized pickers that the shared library cannot represent.
This follows the release-line Select migration brought in by merge 91975b365.

## Completed

- Application usage log: replace the remaining legacy MultiSelect with the real
  @bisheng/ui Select. Keep remote search, 10-item pagination, stable application
  IDs, selection across search results, and tag removal. Discard null/empty IDs
  before constructing options. The endpoint and request parameters are unchanged.
- Permission dialogs and rosters: replace four native selects. Keep the model
  key payload, inactive/current-model display, protected/read-only rows, and the
  add/move/remove mutation contract.
- Approval configuration: replace eight native value selectors (scenario,
  route condition/value/type/flow, selected flow, node modes). The add-approver
  control executes an action, so it uses the shared Dropdown. Preserve no-condition
  selection, required-flow validation, numeric flow IDs, dirty-node confirmation,
  and existing approver sources.
- Remove two implementations with no remaining importers:
  components/bs-ui/multiSelect.tsx/index.tsx and components/ui/select-custom.tsx.
- Regenerate ESLint suppressions with lint:prune; counts only decrease.

## Kept by user decision

| Entry | Reason |
|---|---|
| components/bs-comp/selectComponent/knowledge.tsx | Knowledge/document/space tabs and custom footer |
| pages/BuildPage/flow/FlowNode/component/KnowledgeSelectItem.tsx | Knowledge tabs and business actions in the panel |
| pages/BuildPage/flow/FlowNode/component/SelectVar.tsx | Workflow variable hierarchy and custom content |
| pages/Dashboard/components/config/StyleConfigPanel.tsx | Swatch-only palette previews |
| pages/SystemPage/theme/BrandAssetUpload.tsx | Asset previews and per-option delete actions |

Users.tsx also imports bs-ui/select/filter. That component is a checkbox filter
panel with explicit reset/confirm actions, rather than a value Select; it stays.
The underlying legacy select primitives remain only to support these entries.
No native HTML select remains in platform production TS/TSX sources.

## Manual acceptance by module

- Application usage log: search for an app, select multiple results, search again,
  remove one selected app, scroll to load more, then apply/reset the log filter.
- Resource permissions: grant a permission, change an editable assignee's model,
  confirm protected and inactive/non-grantable assignees remain read-only.
- Approval configuration: add a scenario; edit a branch condition and clear it;
  switch pass/approval, bind a flow and save; change node mode; add an approver;
  switch flows with unsaved node edits and check the discard confirmation.
- The specialized pickers listed above retain their existing interaction.
