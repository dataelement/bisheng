# Subscription state consistency — 2026-10-28

## Scope and source

The reported macOS/13100 symptoms originate in the shared BISHENG platform client and channel services. The Desktop shell displays the embedded platform UI.

Initial analysis baseline: `dataelement/bisheng:feat/bisheng-work-120-main@1a8ac45e1d58a6f0bde7f0fe13552f2beb7b46a1`. Build-verified integration baseline: `c8ae351ee`. The subsequent `8821e490d` assistant-description change was retained before delivery and the channel regressions, client lint and strict types were rechecked. Repair branch: `codex/channel-state-consistency`.

## Behavior

- Detail and square subscription status use effective `visible` permission, matching the followed list and article access checks. Membership rows supply application progress. Organization grants therefore show subscribed; stale ACTIVE records with revoked access show the subscription entry.
- Public subscriptions commit a PENDING membership, project its permission through the existing F048 policy/audit runtime, then activate the membership. A failed projection leaves a retryable subscription entry.
- Manual and automatic approvals use the durable approval outbox. The channel handler activates membership after its permission projection succeeds. Existing execution-failure reporting and retry remain available. The legacy message approval handler follows the same ordering.
- Switching a review channel to public grants access before activating each pending member. Existing restricted administrator roles retain their role and require administrator authorization changes.
- Preview, recommendations and square use server subscription results. Persistent local overrides have been removed.
- Visible active surfaces refresh on focus, visibility restoration and every 30 seconds. KeepAlive activation also refreshes. The square revalidates all loaded pages while retaining the displayed list during requests.
- Open content views close on refreshed access revocation; preview content uses the same access decision. The locked-content message covers both subscription approval and authorization.

## Verification

- Backend targeted set: 55 passed. The same checks against the initial baseline produced 12 failures and 43 passes, including the stale ACTIVE/no-access case, organization access without membership, and failed permission writes.
- Frontend component/hook regression set: 15 cases for approval, revocation, visible/hidden/KeepAlive lifecycle, query invalidation and multi-page square refresh.
- Final combined-branch platform/client lint, strict types, shared-package lint/types, i18n, Ruff, architecture checks and client production build passed. The installed pnpm launcher attempted dependency installation on shared dependency links; the equivalent package-script executables were run directly against the existing dependencies.

## Delivery and acceptance

The user authorized direct integration into `dataelement/bisheng:feat/bisheng-work-120-main`. Release requires the matching backend, approval worker and client assets. Deployment to 13100, real-account approval history/permission data inspection, and native macOS acceptance remain pending.

A deployment smoke should use a regular account and cover pending→approved, approval projection failure→retry, access revoke→regrant, organization grant, and a channel changing from review to public. Compare detail status/actions, followed-list membership and article availability after each transition.
