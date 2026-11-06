# F086 request and discovery record

Date: 2026-10-21. Source: shanghang's instructions in this conversation.
Status: discovery, specification and amended design approved; implementation started.

## Confirmed request

“好，拉一个新分支，抽新的共享包，先抽离工作流和助手，日常和任务不动。
基于client抽，补齐标注 qa等后台操作。”

The preceding analysis recommended a business-specific shared package rather
than moving application shells or state libraries into the UI foundation.
The user selected workflow/assistant as the first scope; this does not authorize
migration of daily/task modes or a UI redesign.

## Verified current entry points

- Client workflow and assistant: `src/frontend/client/src/pages/appChat/`.
- Platform workflow test: `src/frontend/platform/src/pages/BuildPage/flow/FlowChat/ChatTest.tsx`.
- Platform assistant test: `src/frontend/platform/src/pages/BuildPage/assistant/editAssistant/TestChat.tsx`.
- Platform annotation: `src/frontend/platform/src/pages/LabelPage/taskAppChats.tsx`.
- Platform application conversation logs: `src/frontend/platform/src/pages/LogPage/useAppLog/appChatDetail.tsx`.
- Annotation currently invokes `AddSimilarQuestions` for a question and
  `SaveQaLibForm` for an answer, with the matched Q/A and source message ID.
  The first adds a question to selected existing QAs; the second saves a new QA
  to a selected QA library, with optional generated/edited similar questions.
- Platform workflow/assistant already reuse their respective message displays
  within platform; duplication to eliminate is across client and platform as
  well as overlapping workflow/assistant presentation, not a new viewer per page.
- Daily/task message rendering shares some client dependencies with app chat;
  those dependency edges require isolation during design, not incidental migration.

## Branch and baseline

- Base: local `feat/3.0.0`, commit `bdc886930`.
- New branch: `codex/086-shared-app-chat`.
- `feat/3.0.0/086-shared-app-chat` cannot coexist with the existing Git ref
  `feat/3.0.0`; the new branch uses the agent's default prefix instead.
- Pre-existing uncommitted `src/frontend/platform/src/pages/SystemPage/components/Config.tsx`
  remains in place and is unrelated; it must not be included in this feature.
- No package or production-code extraction has started before specification
  and design confirmation required by `docs/SDD-Guide.md` §3.
