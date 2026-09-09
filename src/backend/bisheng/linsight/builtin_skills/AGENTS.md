# Built-in Skill Packs

Auto-loaded when editing files in `src/backend/bisheng/linsight/builtin_skills/`.
Complements `src/backend/bisheng/linsight/AGENTS.md`.

A skill pack is `SKILL.md` plus `scripts/` and `references/`, shipped inside the backend image and
seeded into the skill store at startup. The model reads `SKILL.md` and runs the scripts through the
code interpreter, so these packs are prompt and runtime at the same time — the rules below exist
because a script that merely "works when I run it" can still fail invisibly in that setting.

---

## Script contract

- **Every script must end with `sys.exit(0)` and report its findings on stdout.** The code interpreter is either/or: a non-zero exit returns stderr and throws stdout away, a zero exit returns stdout only. A script that exits non-zero to signal "check failed" therefore deletes its own report and the model sees nothing. Existing scripts already document this at the exit site (`bisheng-pptx/scripts/probe_template.py`, `inspect_deck.py`) — keep doing it. When a script shells out and inspects the result, print stdout and stderr on **separate lines**: `print(r.stdout or r.stderr)` silently drops stderr whenever stdout is non-empty.

- **Call subprocesses through `sys.executable`, not `python`.** `infer_lang` treats code beginning with `python ` or `pip` as shell, and `python` on PATH is not necessarily the backend's venv interpreter.

- **Scripts are stateless across calls.** cwd is the workspace root while the pack lives under `skills/<name>/`, so a script that imports its own helpers needs an explicit `sys.path.insert`. There is no dependency mechanism between skills, and `output/` is the only delivery directory.

---

## Inspection scripts

- **Never introduce a "conditional pass" verdict.** `SKILL.md` tells the model to iterate until the check passes, and any WARN tier inevitably contains shape heuristics and rendering approximations that cannot all be cleared — an unsatisfiable checker makes the model loop until its turn budget is gone. Only ERROR blocks delivery; every new check starts life as WARN.

- **An inspection script must not decide which profile to apply by reading the very field it is checking.** Selecting the document profile from the body font, when a replaced body font is exactly the defect being hunted, makes the check disappear precisely when it should fire. Pick a signal orthogonal to the defect.

- **Where a baseline exists, report the diff, not the raw measurement.** An untouched template that emits hundreds of warnings teaches the model to ignore warnings wholesale; diffing against the baseline drives false positives to zero.

- **Self-test in both directions: a bad sample must trip every check, and a good sample must actually reach a pass.** Testing only bad samples lets "the checker always fails" pass for working.

- **The terminating string the model watches for (a phrase such as a pass verdict) may only be printed by the inspection script.** If another script in the pack prints the same string, the model stops before the inspection runs. Lock ownership down with a static guard test.

---

## Packaging

- **Put no cross-environment assertions in the pack `description`** — it is the only text that reaches the prompt. Statements about what the runtime provides belong in a `SKILL.md` probe step that checks at run time. LibreOffice, pandoc and Chromium come from `base.Dockerfile`, so a hand-built venv or a trimmed image may not have them; depend on them softly and report their absence honestly rather than killing the task.

- **The pack directory name must match the skill slug pattern** (lowercase, digits, single hyphens). Backup or scratch directories must not sit under a pack root — a directory name containing a dot pollutes the skill scan.

---

## Porting an external skill

Three things always need changing, and none of them are dependencies:

1. **Tool names.** This platform's tool set does not contain `run_python`, `file_read`, or a shell tool. Copying an external skill verbatim makes the model call tools that do not exist.
2. **Frontmatter.** Only `name`, `description` and `metadata.display-name` are recognized. Other keys are ignored by the loader but stay in the file and keep misleading the model, so delete them rather than leaving them. A top-level `display_name` is not recognized at all — a display name written there is silently lost.
3. **Import paths.** See the stateless-scripts rule above.

---

## Working method

- **Quality comes from running a real task, rendering the output, looking at every page, and folding what you find back into the inspection script.** It does not come from writing the spec more carefully. Calibrate every threshold against real artifacts; thresholds set by intuition miss defects that are obvious to the eye.

- **Whenever a prompt teaches the model to call a tool a particular way, call it that way yourself first.** A phrase teaching a specific glob spelling sat in the tree for a long time while that spelling matched nothing — the prompt had promoted an existing bug straight to the user. Unit tests do not catch this, because nothing feeds the prompt's literal wording to the tool.

- **Reject an over-limit batch as a whole instead of truncating it.** A truncated batch hands the user a workspace that looks complete and is not. Filter first (hidden files, unsupported types), then apply the limit, so entries like `.DS_Store` do not consume quota.
