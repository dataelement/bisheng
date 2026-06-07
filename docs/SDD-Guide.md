# SDD Guide — Spec-Driven Development Workflow

> The full spec for how features get built in BiSheng. Root `AGENTS.md §6` is the quick-reference flow; **this file is the authoritative detail and the single source for the workflow**.
> Architecture laws every feature must obey → `docs/constitution.md`. Document templates → `features/_templates/`.
>
> **Status convention**: items marked **✅** are live today; **🚧** are planned and **must not be assumed active**. Full status list → §8.

---

## 0. Background & rationale

This workflow replaced an earlier "scattered / duplicated / mixed" doc setup. Three moves:
1. **One source per fact** — laws in `constitution.md`, architecture in `docs/architecture/`, coding conventions in each `AGENTS.md`. No fact has two homes.
2. **Load on demand** — sub-project rules auto-load by directory (editing backend loads `src/backend/AGENTS.md`, etc.), so context isn't flooded.
3. **A harness** — so the agent runs long stretches unattended (self-checks, self-fixes), and the human stays on key decisions + final judgement.

**Key lesson (why the ✅/🚧 split exists):** an "architecture guard" everyone assumed was running had in fact been **silently dead for months** (non-existent hook variable + a hardcoded path to someone else's machine). It was caught only by deliberately triggering a violation and checking. → **Never trust "should be running"; verify "is running."** Every harness piece below is therefore marked live or planned, and planned ones are not to be relied on.

---

## 1. Pick the track (流程分级) ✅

Not every change runs the full pipeline. Match track to scope:

| Track | When | Steps |
|---|---|---|
| **Hotfix / trivial** | bug fix, copy/text change, dep bump, ≲ 1 file of logic, **no contract change** | branch → fix → arch-guard + smoke pass → `/code-review` → merge. No spec/design/tasks. |
| **Small feature** | single module, no cross-feature contract, low uncertainty | lightweight `spec.md` (AC list) → implement → `/e2e-test` → review. Decisions/gotchas: record in the PR, or a short `design.md` if non-trivial. |
| **Full SDD** | new capability, cross-module, new/changed contract, or touches a constitution clause | full pipeline (§2) |

**Rule of thumb**: if you'd change a **contract others depend on**, or **revisit a constitution law (C1–C7)**, it's Full SDD. When unsure, ask the user which track.

---

## 2. Full pipeline

```
0. (version's first feature only) release-contract.md  +  read docs/constitution.md
1. Spec Discovery (agent explores code, asks one key decision at a time)  →  ★ user confirms
2. spec.md  (What only; no tech stack; [待澄清] markers; EARS-style testable AC 🚧)
        →  /sdd-review <dir> spec  →  ★ user confirms
3. design.md  (only this feature's How; global laws → reference constitution)
        →  /sdd-review <dir> design  (Constitution Check gate, §5 🚧)  →  ★ user confirms
4. tasks.md  (vertical slices; dependency waves 🚧)  →  /sdd-review <dir> tasks
5. branch: feat/<version>/{NNN}-{name}   (create EARLY — docs + code live on the branch)
6. implement  →  /task-review <dir> <id>  →  check off
        — harness auto-catches violations & runs smoke (§6); deviations handled per §4
7. /e2e-test <dir>   (mandatory; frontend = Playwright 🚧)
8. /code-review --base <main>   (+ CI auto-review 🚧)
9. merge
```

---

## 3. Pause points (★) — human-in-the-loop ✅

★ = a **mandatory stop; the agent cannot skip it**. Key decisions can't be made by the machine alone.

Three fixed ★: after Spec Discovery, after `spec.md`, after `design.md`.

**Fourth, dynamic ★ — deviation re-confirmation:** during implementation, if a deviation **overturns something the user already signed off on** (a spec AC, or a design decision), **stop and re-confirm** — don't silently rewrite an agreed decision.
- Overturns a signed-off decision → **stop, re-confirm** (human–AI alignment is broken; re-align).
- Minor implementation detail only → just update `design.md` + note it, no stop.

> Note: the fourth ★ currently relies on agent/human discipline — there's no tooling enforcing it yet (🚧).

(`tasks.md` has no ★ — it's an execution checklist; `/sdd-review tasks` is enough.)

---

## 4. Document roles & the design philosophy ✅

| Document | Answers | Update rule |
|----------|---------|-------------|
| `spec.md` | What & acceptance criteria | Only when requirements change |
| `design.md` | Why this How + today's-state snapshot | **Overwrite in place** — always reflects today |
| `tasks.md` | What was done, in what order | Append — running log |

**The design.md philosophy (important):**

`design.md` keeps **only today's state** — overwrite it, never keep old-design snapshots. The next person reads the latest and nothing older. **BUT** for every key decision it must record:
- **why this option, not the rejected alternatives** (and *when to reconsider*), and
- **known gotchas** — "tried A, breaks on X, so B" (the §5「已知坑」 section).

This is **not** history-keeping — it's a **guardrail so the next person doesn't re-walk a proven dead end.**

> Example (F028): PDF engine switched libreoffice → chromium. If design kept only "uses chromium", someone would later ask "why not the simpler libreoffice?" and revert — back into the table-layout breakage. The decision record + gotcha blocks that. **Keep the reason, drop the old snapshot.**

**Deviation log (`tasks.md §实际偏差记录`) — lightweight:** the reasoning lives in `design.md`; the tasks log needs only a one-line pointer ("T7 deviated → updated design decision 6"), or rely on the PR. **Never duplicate design's argument in two places.**

---

## 5. Constitution gate 🚧

**Target**: `/sdd-review design` runs a **Constitution Check** — does the design violate any law C1–C7 in `docs/constitution.md`? A violation is a **BLOCKER**. To be folded into the existing `design-checklist.md` (not a separate gate). **Not yet implemented.**

---

## 6. Harness — what's automatic during implementation

The harness lets the agent run a long stretch without the human relaying results:

- ✅ **arch-guard hook** feeds rule violations back as `additionalContext` → agent self-corrects (`.claude/hooks/arch-guard-hook.sh`; verified end-to-end).
- 🚧 **Stop hook** runs the no-dependency fast tests (seconds: backend unit + frontend component) → agent fixes until green. Heavier tiers go to central regression (see Test tiers below).
- 🚧 **Adversarial review subagent** — checks the diff in an independent context (incl. "does the diff contradict design.md?").
- 🚧 **Frontend Playwright** interaction tests assert behavior; humans only judge look / feel / UX.
- ✅ **Circuit breaker** — any hook can be disabled fast (env flag / settings comment) if it misfires.

**Test tiers** (the split is "external dependency or not"):
- **PR gate** (every PR, fast, no external deps): backend unit + frontend component (Vitest) + ruff + arch-guard. → can be wired now without middleware; 🚧 CI job not yet added.
- **Central regression** (pre-release / periodic, needs full env): DM8 full + middleware integration + API e2e + Playwright. → **not in per-feature gates by design** (constitution C2). 🚧

---

## 7. Doc-drift prevention (incl. hotfix path) 🚧

Biggest drift risk: **hotfixes that skip SDD** — code changes, nobody updates design. Planned mitigation:
- A change hitting a file/symbol covered by a design decision/contract/gotcha → review subagent flags "diff vs design mismatch".
- A hotfix that reveals the original design was wrong → update the design decision **and add a known-gotcha** ("why the old approach fails"). Highest-value gotcha source — learned by getting burned.

---

## 8. Status & Roadmap

**✅ Live now:**
- Doc layering: `constitution.md`, slimmed root + per-subproject `AGENTS.md`, this guide, `docs/architecture/` ownership.
- **All three feature templates on the new model**: spec = What-only, P0/complex AC in EARS form (small features use table form); design = decisions+gotchas referencing constitution + deviation tiering; tasks = wave organization + one-line deviation log.
- arch-guard hook feeding violations back to the agent (verified end-to-end).
- Track selection (§1); three fixed pause points (§3); circuit breaker; `/sdd-review` · `/task-review` · `/e2e-test`.

**🚧 Planned (not active — do not assume):**
- Constitution Check folded into `design-checklist.md` (§5). `/sdd-review spec` does not yet enforce EARS on P0 specs (convention only for now).
- Stop hook self-fix; adversarial review subagent; Playwright frontend tests; CI auto-review; doc-drift subagent (§6, §7).
- **CI today only builds/pushes images — no test/lint/arch-guard gate yet.** The PR fast-test gate (backend unit + frontend component + ruff + arch-guard) can be wired now without middleware; DM8 / integration / e2e wait for the central-regression env (see constitution C2).
- Deviation re-confirm / drift enforcement is tooling-only-planned — templates already prompt it, nothing enforces it yet.

**Open decisions:**
- ~~EARS enforcement scope~~ — **decided: EARS for P0/complex features, table form for small ones.**
- tasks dependency format (markdown waves vs JSON) — leaning markdown.
- Visual-regression testing — deferred.
- CI must bring up the full middleware stack (+ DM8) before the CI/Stop-hook items can land.

> Each 🚧 item should land with a minimal eval (does it actually reduce human intervention?) before being treated as ✅ — see §0 lesson.
