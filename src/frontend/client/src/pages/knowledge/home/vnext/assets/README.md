# Knowledge home asset mapping

Light-mode source: project-level `design/asset/`, updated 2026-11-03. Dark-mode source: the three user-supplied `Space icon · blue/green/orange.png` files, added 2026-11-04. All supplied assets are copied byte-for-byte. Some SVGs are retained as inactive design references after adopting shared components and library icons; active mappings are listed below.

- `card-1.png`, `card-2.png`, `card-3.png`: 88×88 (2×) PNGs, mapped respectively to department, created and joined API sources through `knowledgeSpaceIcons.ts`. Desktop cards and mobile list rows share this mapping. At 1440px they display at 34×34px; mobile rows display at 32×32px. Rasterized blur and translucent layers match the exported design. The experimental card SVGs are inactive and are not required by this change.
- `space-department-dark.png`, `space-created-dark.png`, `space-joined-dark.png`: 132×132 RGBA PNGs for dark mode, mapped respectively from the supplied blue, orange and green files. `KnowledgeSpaceCategoryIcon` follows the app's resolved `.dark` class through native Tailwind visibility variants, so manual and system theme changes use the same artwork in desktop cards and mobile rows. Light-mode artwork and display sizes stay unchanged.
- `menu-1.svg`, `menu-2.svg`, `menu-3.svg`: inactive design references. Tabs now use `bisheng-icons` 0.2.37's `Filled.Departure`, `Filled.Person`, and `Filled.Tag` for department, created, and joined. The shared medium Tabs supplies 16×16px sizing and currentColor selection states.
- `menber.svg`: inactive design reference. Creator metadata now uses `bisheng-icons`'s `Outlined.People` at 14×14px, alongside 12px creator and update text.
- `Clip.svg`, `clip-2.svg`: square 20×20 canvases for pinned / unpinned state, displayed at 12×12px at 1440 after the requested 80% reduction and downward even-pixel quantization. They now act as CSS alpha masks: the original shapes and stroke opacity remain, while the visible color inherits the shared `text-3` token. The button hit area remains independent. `clip-2-hover.svg` derives from the supplied outline by changing only stroke-opacity from .5 to 1. Unpinned icons remain hidden until card hover/focus, while pinned icons remain visible.
- `more.svg`: inactive design reference. The shared small icon-only Button now uses `Outlined.More` at its native 14×14px size.
- `sort-arrow.svg`: earlier local fallback arrow retained; the active shared Select uses its own chevron.

CSS geometry rounds down to even pixels independently of typography; SVG internal coordinates and opacity values are not rounded. Current card title is 14px, card padding is 16px on all sides, and the authoritative revision history is in `docs/knowledge-space-design-spec.md`.

## SHA256 of supplied files (including inactive references)

- `card-1.png`: `1fda19627df95ef8292a2aeaea3560aa6c13b8837f43719401f5809393a3615c`
- `card-2.png`: `ae5b08860b39b78238478f9df16cb32fb2c710177f5671b4ff03b8c0c9d6fe2a`
- `card-3.png`: `b036d17bc56a50d2b7f14a75ea92ac2d107be2d74eb0ef23901d8feef7541764`
- `space-department-dark.png`: `4f3f1efd0970a5e377c8c7f8f547f42e62229d598ba763caf18c762c0c64b9ab`
- `space-created-dark.png`: `8d8aaae67af169e4d96096a1815cf56a5e3ad6d4e333bb0fb1e24e2bd73dea6a`
- `space-joined-dark.png`: `786b3049526482498b8890a00860425399561b4befb5cf3d3d7f5bc21b9e0d06`
- `menu-1.svg`: `0972568f833f35123f7c0766a468cf3d618ff964f1a585684b2af14d16a2f5f1`
- `menu-2.svg`: `c37ad9f8df575098da64237ae53d1bf17c9c228a6ae7359b7ff47a7c93598310`
- `menu-3.svg`: `aa4a72cac60654384f137640b229102c32309766105547d4d9ba5c5f19716d7f`
- `menber.svg`: `7e7233cccd851cef70827a9510b44e27f7b86e79693a6d388fbb33d73d687794`
- `Clip.svg`: `cd2cd4b31612718c042d807fe9226c5fe65b83dad54d45cc7f7d8625332e1898`
- `clip-2.svg`: `cb027939cf64b174ce2c21c13a7c1754a15fca47dcbba27e1e20dc88ee3d927f`
- `more.svg`: `a236cbac8ba1348199857300c46b59f1547a997692f9be1b83d35c342e2ef83e`
