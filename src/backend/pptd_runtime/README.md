# PPTD engine runtime

The built-in task-mode skill `bisheng-pptx` ("PPT 制作") writes decks as PPTD projects and calls
this engine to check and export them (`builtin_skills/bisheng-pptx/scripts/pptd.py`).
Design and rationale: `features/v3.1.0-beta1/014-pptx-pptd-engine/design.md`.

| Path | What |
|---|---|
| `dsh-ppt/` | Vendored engine: `lib/`, `LICENSE` (MIT), `THIRD_PARTY_NOTICES.md` from `dataelement/dsh-desktop` `packages/ppt-runtime/core` at commit `46666d3` (package version 0.1.1-rc.2). Do not edit by hand. |
| `package.json` / `package-lock.json` | The six npm packages the CLI's import chain needs. The upstream peer deps (cordis, dsh-*) serve the desktop plugin entry only and are not installed. |
| `install.sh` | Installs everything to `/opt/pptd-runtime` on a source deployment. |

Runtime layout (image and `install.sh` alike):

```
/opt/pptd-runtime/bin/node
/opt/pptd-runtime/node_modules/      <- base.Dockerfile (npm ci)
/opt/pptd-runtime/engine/lib/bin.js  <- Dockerfile (COPY of dsh-ppt/)
```

The engine must stay outside `node_modules/`: `npm ci` deletes anything there that is not in
`package.json`. Node resolves the engine's imports by walking up to `/opt/pptd-runtime/node_modules`.

## Updating the engine

1. In dsh-desktop, pick the commit and copy `packages/ppt-runtime/core/{lib,LICENSE,THIRD_PARTY_NOTICES.md}`
   over `dsh-ppt/`; update the commit above.
2. If the CLI's imports changed, update `package.json`, regenerate the lock with
   `npm install --package-lock-only`, and bump the base image (`base.vN` tag).
3. Run `test/linsight/test_pptx_pptd_skill.py` with the engine installed and rerun the four comparison prompts.
