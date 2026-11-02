# Knowledge home original asset mapping

Source: `/Users/yxwang/Desktop/bishengproject/design/asset/`. All ten original files are copied byte-for-byte with original spelling and case (including `menber.svg`). No paths, colors, viewBoxes or PNG pixels are modified. The former `space.png` copy was identical to `card-1.png` and is replaced by the original filename.

Figma source: file `ceyPGsiRutsoQcjHleUkl3`, frame `159:8513`. Design context and screenshot were retrieved again during this implementation. The approved normalized visual values remain those in `docs/knowledge-space-design-spec.md`, not the raw frame's inconsistent values.

## Files, geometry and callsites

- `card-1.png`: original88×88 (2×), displayed44×44 with the existing fixed icon slot. Confirmed category: organization/department; existing `/api/v1/knowledge/space/department` list. Figma reference `141:4199`. SHA256 prefix `1fda19627df9`.
- `card-2.png`: original88×88 (2×), displayed44×44 with the existing fixed icon slot. Confirmed category: created by me; existing `/api/v1/knowledge/space/mine` list. Figma reference `141:4092`. SHA256 prefix `ae5b08860b39`.
- `card-3.png`: original88×88 (2×), displayed44×44 with the existing fixed icon slot. Confirmed category: joined; existing `/api/v1/knowledge/space/joined` list. Figma reference `141:4124`. SHA256 prefix `b036d17bc56a`.
- `menu-1.svg`: root14×14, viewBox `0 0 14 14`, path/group opacity retained. Figma `141:3955`, organization/department Tab. `KnowledgeHomePage.tsx` maps it to the existing `department` category. SHA256 prefix `8c80513960b4`.
- `menu-2.svg`: root14×17, viewBox `0 0 14 17`; visible geometry reaches y≈16.4165 (transparent bottom remainder retained). Figma wrapper `141:3961`, inner user `141:3962`, created Tab. Mapped only to `created`. SHA256 prefix `24df87a9f6ee`.
- `menu-3.png`: 18×18; nonzero alpha bounds [0,0,18,18). Figma `141:3969`, joined Tab. Mapped only to `joined`; the tag shape does not create a tag-based business classification. SHA256 prefix `eef405ce1dc7`.
- `menber.svg`: root20×20, viewBox `0 0 20 20`, paths inset with stroke and natural whitespace. Figma `141:4191`, before creator/team text. Rendered only when `departmentName.trim() || creator.trim()` is nonempty. It does not represent `memberCount`. SHA256 prefix `2b402932ed0d`.
- `Clip.svg`: root24×24, viewBox `0 0 24 24`; masked filled pin, inset path and1.6 stroke retained. Figma `141:4183` (filled pin also appears in the hover example). Used for `space.isPinned=true`. SHA256 prefix `314b7c293ffb`.
- `clip-2.svg`: updated original outline pin, root25×24, viewBox `0 0 25 24`; replaces the previous24×24 PNG and preserves its natural aspect ratio. Figma slot `141:4133`; used for `space.isPinned=false`.
- `more.svg`: root30×30, viewBox `0 0 30 30`. Three circles at x7/15/23, y16, r2, so exact painted union spans x5..25, y14..18. Figma `159:8514`. The original image remains30×30; a local20×4 overflow-hidden slot translates it by(-5,-14). The button hit area stays28×22 in the footer. This implements the user's confirmed20×4 glyph without distortion or editing the asset. SHA256 prefix `e792ffc1acc9`.

The previously recorded menu PNG bounds were decoded directly from alpha bytes; SVG geometry was inspected from the original viewBox/path/circle data. Local assets were checked against source bytes, then checked for successful browser loading and rendered dimensions.

## State basis

- Default card #F7F9FB, hover #EFF2F8, pressed same as hover: frozen spec §3.1/3.4, no scaling or shadow. Card geometry and all surfaces/padding/gaps/radii use CSS.
- Focus: frozen2px #333, offset2px. The primary open-space button's pseudo-element outlines the whole card; other controls use their local focus-visible rules. No dimensions change on focus.
- Pinned: existing `space.isPinned`, existing pin/unpin action and pending/rollback logic. Filled versus outline is an explicit semantic mapping of the supplied pin assets; Figma contains those shapes but no formal pinned/unpinned component variant definition. It is not inferred as a hover effect. No special pinned card background is introduced.
- Tab: existing selected category drives `aria-selected`, frozen #E3E7EE selected background and500 weight; default text black60%, hover #F7F9FB. Raw Tab glyph opacity is preserved in both states because no alternate icon-state assets were provided.
- Buttons: frozen default/hover/pressed/disabled colors and40px control geometry. Dedicated semantic tokens now exist even when values coincide. No extra icon-button hover background is inferred from the screenshot.
- Shadow: explicitly `none` for cards and controls, matching inspected effects and frozen spec. Portal menu still opts into the same scoped tokens. No new popup/danger/empty/error palette or shadow has been invented.

## Differences and unresolved inputs

- The user has now confirmed all three category mappings: organization/department uses the existing department API; created uses mine; joined uses joined. Artwork is selected from each card's existing `HomeSpace.source`, including the merged all-spaces view. The existing department > created > joined deduplication precedence is unchanged.
- The three category illustrations now intentionally take precedence over `space.icon` on this homepage. No backend mapping, custom-image URL resolution or extra request is added. Detail/mobile pages keep their existing imagery behavior.
- Original pin/member/more glyph color #6A7588 is preserved; normalized text remains #626E82. No alternate active Tab or disabled/pending icon assets are supplied.
- Sorting now uses a user-requested local12x8 rounded triangle, #333333, and page-scoped Radix Select instead of the native arrow. Create keeps the existing shared Plus icon.
- CSS specifies the approved PingFang SC stack and400/500/600 weights. `document.fonts.check` alone does not establish the actual fallback/physical font, so exact cross-platform glyph rasterization remains unverified.
- No live backend or host Sidebar integration was exercised. Browser validation uses the actual homepage with clearly marked fixture data. The known MainLayout missing useGetBsConfig import still blocks a clean application typecheck.

## Browser validation for this pass

- The legacy global narrow-viewport select font-size16!important is overridden only by this page's own sort class to keep the frozen14px even inside a narrow desktop host. Mobile knowledge pages and global rules are unchanged.
- C1531, grid1419: three columns, first card446.328125×176, padding24, radius16, shadow none, default rgb(247,249,251).
- The previous pass loaded all eight then-available assets; the updated pass checks all ten assets across the three categories. Effective sizes: Tab14×14 /14×17 /18×18; card44×44; filled pin24×24, updated outline pin25×24; owner20×20; original more30×30 with visible slot20×4.
- Clicking the fixture card left its hover state at rgb(239,242,248). Keyboard focus on the main card action produced a2px rgb(51,51,51) outline with2px offset on the full-card pseudo-element.
- Test-only preview now offers a `First card pinned` switch to inspect both original pin assets without changing any backend state.

## Asset refresh confirmation

User supplied three88×88 originals and confirmed category-to-API mapping. Card slot dimensions, tokens, M/G/page padding and business list/query behavior remain unchanged. The former orange/green asset and category-mapping gaps are resolved.

## v1.5 local interaction assets

The ten original files remain byte-for-byte copies. Two separate assets were added:
- `clip-2-hover.svg`: original outline geometry and25x24 canvas, changing only stroke-opacity .5 to1; original SVG remains untouched. CSS swaps decorative image layers while an enabled unpinned button is hovered.
- `sort-arrow.svg`: explicitly requested12x8 triangle, #333333,2px round-joined outline for1px corner radius. It is authored locally, not attributed to Figma.

More opacity .6 on hover/press/open; create opacity .6 on hover. Sort border #333 on hover/open, #D0D5DE when closed and not hovered; no outer ring/shadow after closing. Keyboard focus retains a text underline. These explicit user instructions supersede prior native-arrow and absent-hover descriptions.

## v1.7 light-mode interaction revision

The user resized the authored sorting arrow to8x4; file root/viewBox and rendered dimensions now match8x4. Color stays#333333 and rounded joins remain. Previous12x8 references describe the superseded version. Knowledge Square hover and sort hover/open now fill5% #333, with unchanged border and whole-control opacity1. Previous hover border-opacity/darkening rules are superseded. Accepted dark Figma previews are not modified by this code change.
