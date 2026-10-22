# F086: Shared workflow and assistant conversations

**关联 PRD**: [Confirmed user request and discovery](request.md)
**优先级**: P1
**所属版本**: v3.0.0
**状态**: Reviewed and user confirmed, 2026-10-21
**依赖**: Existing workflow/assistant conversations, annotation and QA management;
F078 shared UI foundation. Architecture rules: [constitution](../../../docs/constitution.md).

## 1. Scope and user stories

As an application user, I want workflow and assistant conversations to retain
client behavior after extraction, including interactive forms and history.
As an application builder, I want a consistent conversation in the test panel.
As an annotator, I want to review conversations and reuse questions/answers in
QA libraries without losing message identity or annotation controls.
As an administrator, I want to inspect conversation history without executing it.
As a maintainer, I want one shared implementation for workflow/assistant message
presentation and common interpretation, consumed by both applications.

Included: client workflow/assistant conversations; their platform test panels;
workflow/assistant annotation; existing application conversation log/detail
viewing; messages, attachments, citations, reasoning, run details, interactive
forms/choices, input and common event/history interpretation used by these modes.
The visual/interaction baseline is the current client implementation, with
platform-only operations added for the relevant authorized hosts.

Excluded: daily chat and task/Linsight migration; new state-management libraries;
application navigation/sidebars; new annotation or QA business rules; permission
model changes; backend schema/API changes; redesign of shared UI components.
Changes needed to those excluded contracts must be raised separately.

## 2. Acceptance criteria

### 2.1 Shared behavior and scope

- **AC-01** — THE SYSTEM SHALL use the same shared workflow/assistant message
  presentation and common message interpretation in client, platform tests,
  annotation and application log viewers, retiring the replaced production
  implementations rather than maintaining two rendering paths for those modes.
- **AC-02** — WHEN an existing workflow or assistant is opened in client, THE
  SYSTEM SHALL retain its current sending, stopping, continuation where
  supported, file handling, history pagination, application version selection,
  feedback, citation and sharing behavior for the current access mode.
- **AC-03** — WHEN a builder opens a workflow or assistant test panel, THE SYSTEM
  SHALL preserve its unsaved configuration/parameters, test initialization,
  clearing, sending, stopping and supported continuation behavior.
- **AC-04** — THE SYSTEM SHALL retain the client visual/interaction baseline for
  shared messages while allowing each host's surrounding layout and authorized
  operations; both light/dark and existing narrow-screen layouts SHALL remain usable.
- **AC-05** — THE SYSTEM SHALL leave daily/task mode source implementations and
  their sending, history, execution, artifact and shared-view behavior unchanged.
  Any dependency shared with those modes SHALL preserve its existing contract.

### 2.2 Message correctness and interactive behavior

- **AC-06** — WHEN live or historical messages are displayed, THE SYSTEM SHALL
  preserve message identity, order, roles, text, reasoning, references,
  attachments, node/run details and applicable interaction state without
  dropping messages or duplicating final answers after streaming completes.
- **AC-07** — WHILE a workflow waits for a form or choice in an interactive
  conversation, THE SYSTEM SHALL validate and submit the selected values once,
  retain submission/disabled state and continue the correct conversation.
- **AC-08** — WHILE new messages arrive, THE SYSTEM SHALL retain scroll-follow
  behavior without pulling a reader away from older messages; loading older
  history SHALL preserve the reader's position and avoid duplicate entries.
- **AC-09** — WHEN citations, uploaded files or generated files are opened, THE
  SYSTEM SHALL preserve the correct resource target and existing access checks;
  denied, expired or unavailable content SHALL not appear as a successful empty preview.
- **AC-10** — IF a connection, stream, parse or server error occurs, THEN THE
  SYSTEM SHALL display the applicable existing failure state and allow only the
  retry/continuation actions supported in that host, without silently creating
  a substitute answer or switching to an unrelated conversation.

### 2.3 Platform annotation and QA operations

- **AC-11** — WHEN an authorized annotator selects a question's annotation
  action, THE SYSTEM SHALL offer adding that question to selected existing QA
  entries as a similar question, preserving the selected conversation and text.
- **AC-12** — WHEN an authorized annotator selects an answer's QA action, THE
  SYSTEM SHALL prefill its matched question and answer for saving a new QA to
  a selected QA library; existing similar-question editing/generation and
  submission validation SHALL remain available.
- **AC-13** — WHEN a QA action is triggered, THE SYSTEM SHALL associate it with
  the correct source message and question/answer pair, including multi-turn,
  streamed, form/choice and interleaved run-detail conversations; it SHALL not
  accidentally use an adjacent system/tool message as a question or answer.
- **AC-14** — WHEN an annotator changes status or navigates previous/next, THE
  SYSTEM SHALL retain existing assignment restrictions and status choices, and
  clear stale message/action state on conversation change; a failed QA write
  SHALL not be reported as successful or mark the conversation complete.
- **AC-15** — WHERE the host has no annotation/QA capability, THE SYSTEM SHALL
  expose no annotation/QA write action, including ordinary client and log views.

### 2.4 Read-only behavior, isolation and compatibility

- **AC-16** — WHILE viewing logs/audit history or a read-only shared conversation,
  THE SYSTEM SHALL permit authorized reading/copying/previewing but SHALL NOT
  send messages, execute historical forms/choices, open a live generation
  connection, stop a run or resume execution merely by mounting or interacting
  with historical content.
- **AC-17** — WHEN conversations are switched or multiple conversation panels
  coexist, THE SYSTEM SHALL keep messages, drafts, stream state, pagination,
  file selections and annotation targets isolated to their conversation/panel.
- **AC-18** — THE SYSTEM SHALL preserve current identity, tenant, resource and
  share-access checks for reads and writes; shared presentation SHALL NOT grant
  access based on visibility of an operation button.
- **AC-19** — THE SYSTEM SHALL preserve Chinese, English and Japanese copy for
  the shared features and host actions; newly introduced copy SHALL be available
  in all three languages without leaking application-internal labels.
- **AC-20** — WHEN both applications are built and tested, THE SYSTEM SHALL
  consume the shared implementation successfully; regression coverage SHALL
  include both modes in client, both platform test panels, annotation/QA writes,
  log read-only viewing and concurrent/switching conversations, together with
  unchanged daily/task smoke coverage.

## 3. Boundary cases

Historical applications may be deleted, data may use older message formats,
files/citations may be denied or expired, and streams may be interrupted.
These cases preserve existing visible failure behavior and available history;
missing fields do not authorize inventing content or permitting execution.

A conversation may have multiple output messages between two user inputs.
Annotation must maintain the chosen answer's identity and corresponding question.
Readonly access disables execution, not legitimate citation/file access.
A successful QA write is required before the related completion is reported.

## 4. Next documents

Design decisions, package contracts and adapters belong in `design.md` after
specification confirmation. Implementation waves and AC-linked verification
belong in `tasks.md` after design confirmation. The design is confirmed; `tasks.md`, `verification.md` and `e2e-checklist.md` track implementation and acceptance evidence.
