# Application building migration

Scope: BuildPage root app/template pages, assistant creation/editor, tools and
built-in tool configuration, plus directly owned card/sheet compositions, publishing integration guides,
content-security settings and assistant debug chat/voice/citation controls.
Workflow canvas, node/debug/chat controls belong to module 4; bench configuration
belongs to module 13; plugin market belongs to module 12.

User-approved cadence: Knowledge remains under user testing while this module
is developed. Prioritize incoming Knowledge fixes. Keep heavy checks serial.

## Tasks

- [x] Migrate finalized tool/assistant selection controls and tooltip compositions;
  preserve custom tooltip triggers and rich parameter descriptions.
- [x] Migrate app/tool textual labels to shared Tag where applicable.
- [x] Replace suitable business icons, preserving unmatched icons explicitly.
- [x] Split the oversized custom tool editor without changing schema/auth/test flows.
- [x] Verify tool auth/provider changes, assistant settings and lazy permissions;
  run scoped lint, types, build and read-only review.
- [x] Record full-module acceptance checklist and retained gaps.

Ruling: retain existing form mechanisms and API contracts. Shared component
migration does not change when settings are saved, permissions or tool execution.

## Acceptance checklist

- Applications: search/filter/tags, creation, editing metadata/avatar, copy/delete,
  template management, version selection and publish/unpublish. Check rejected
  changes keep the current switch state and clicking it does not open the card.
- Templates: list, drag order, creation/deletion and creating an app from a template.
  Existing drag/table/dialog implementations remain; foundation inputs/buttons
  already use shared adapters.
- Assistant: model/temperature/token settings, prompt generation and application,
  opening statement/questions, knowledge-space permissions, tools and content
  security. Switch editor/publishing views, save/cancel and test the debug pane.
- Tools: built-in/custom/MCP lists, search, lazy management permissions, create/edit,
  schema example/import, authentication mode and location, API testing and save.
- Built-in configuration: image provider, sandbox execution/provider, web search,
  crawler, email, Feishu, Bing, Tianyancha, Jina, SiliconFlow, finance and image-view.
- Publishing: identity/example-language tabs, copying code/links, guest-link
  enable/disable and existing expiry/access controls.
- Debug: send/clear/upload/stop, reasoning/run logs, citations and document preview,
  voice input/playback where the test environment has the models configured.

## Retained gaps

Keep unfinalized Table, Select/Cascader, ordinary Dialog/Sheet, Popover,
DropdownMenu, Accordion, Slider, Card, drag/drop and upload/editor implementations.
Keep the existing inline Alert/skeleton and confirmation service. Workflow-only
API documentation (ApiAccessFlow/ApiWorkflowEvents) belongs to module 4; obsolete
skill guide is not rewired by this migration. Generic permissions UI belongs to
system administration; assistant-specific content-security controls are included.

Unmatched icons remain: Shield, CpuIcon, Star, CircleMinus, Bookmark and FlagIcon.
Configurable LoadingIcon branding, the animated VoiceRecordingIcon and specialized
citation/file-type renderers are retained. Static default assistant/workflow/user
icons and equivalent copy/send/clear/loading/preview controls use bisheng-icons.

## Verification record

- 10 module interaction tests passed: image-view model selection, lazy tool
  permissions, sandbox/provider selection, image provider fields, publish
  rejection/success, assistant editor tabs/readonly visibility, API identity headers,
  selected example language and copying the visible example.
- Isolated Chromium checks passed with mocked APIs: publish success/rejection,
  no accidental card navigation, sandbox/provider radios, identity/language tabs,
  and light/dark tooltip contrast. No page JavaScript errors. Fixture removed and
  browser closed. No actual publish, guest-link, tool or chat requests were sent.
- Independent read-only review passed, including the added assistant debug,
  citation and voice icon scope. No newly introduced actionable findings.
- Existing nested DialogClose/AccordionTrigger control warnings remain outside
  this migration's component shells; ordinary dialogs/accordion are retained gaps.
- Three old Chinese UI strings now use existing flow translations; no new keys.

- Combined Knowledge/application/assistant regressions: 41 tests passed across 16
  files. Full frontend typecheck passed (platform 614 strict files, client 1368,
  file-viewers). Final scoped ESLint passed with no suppression increases.
- Full frontend lint remains blocked by 93 pre-existing errors and one warning
  outside this module (API, builder workflow/workbench, license tests and generic
  permission/select components). It stops before checking the other workspaces.

- Final platform production build passed; existing oversized-chunk and third-party
  xlsx-populate eval warnings remain. Dev server stays available at
  http://localhost:3001/build/apps and /build/tools, with the existing 120:3002
  proxy. Module 3 is ready for user acceptance; Knowledge remains under testing.
