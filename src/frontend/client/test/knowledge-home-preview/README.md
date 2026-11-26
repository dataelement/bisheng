# Knowledge home responsive validation

Run from `src/frontend/client`: `node test/knowledge-home-preview/server.mjs`.
Open http://127.0.0.1:4175/test/knowledge-home-preview/.

This isolated harness renders the actual KnowledgeHomePage with the application's global CSS and page CSS modules. Only its data, permission and mutation dependencies are replaced. All records are explicit fixtures; no backend writes occur. The left slot simulates geometry, not the actual Sidebar component. It is not included in the production entry point.

## Historical fixed-minimum measurements (superseded by v1.2)

All dimensions below are CSS pixels, measured from browser DOM rectangles and computed styles. C is the right page's border-box width; W is the grid width after the two 56px page paddings. M=440, horizontal/vertical G=40. Overlay scrollbars in this browser consume no layout width.

- Outer 1920, reference navigation slot 389: C=1531, W=1419, 3 columns, first card=446.328125.
- Outer 1920, existing Web navigation slot 240: C=1680, W=1568, 3 columns, card=496.
- Outer 1920, no navigation slot (maximum available content): C=1920, W=1808, 3 columns, card=576.
- C=1031: W=919, 1 column, card=919. C=1032: W=920, 2 columns, card=440.
- C=1511: W=1399, 2 columns, card=679.5. C=1512: W=1400, 3 columns, card=440.
- C=1991: W=1879, 3 columns, first card=599.6640625. C=1992: W=1880, 4 columns, card=440.
- C=2560: W=2448, 5 columns, first card=457.59375.

Thresholds are derived from available grid width: n*M+(n-1)*G, with page threshold adding 112px. Thus 2/3/4/5 columns start at C=1032/1512/1992/2472 respectively; both sides of the 2/3/4-column thresholds were browser-tested. No Sidebar state or viewport breakpoint selects the column count.

## Edge cases

- At C=1531, zero records displays the actual empty state without a grid. One and two records retain all three auto-fill tracks; cards remain 446.328125px instead of stretching across missing tracks.
- Long unbroken titles, descriptions and owners were tested at C=800/600/480/360/320/260/240. No page horizontal overflow. Titles and descriptions truncate; metadata may wrap and cards may grow vertically.
- Fixed dimensions remain title font 18px, space icon 44px, card padding 24px throughout narrow tests. At C=320/260/240, title widths after the local heading-wrap repair are 160/100/80px (previously zero at C=260/240).
- The page title has a 240px flex basis, allowing the header actions to move to the next line instead of squeezing the heading to individual characters. A long English page heading was also used to expose this case during validation; the final preview uses the existing localized knowledge-space label.
- At C=600, Tab client width=488 and scroll width=578 for seven records; sorting wraps below the tabs. End selects/focuses the final Tab and scrolls it into view (scrollLeft approximately 86.26; final Tab right approximately 539.86, container right 540). Home returns to the first Tab.
- With 72 records at C=1531 and panel height720, scrollHeight=5432. Keyboard scrolling moved the page scrollTop to2444 while document scrollTop remained0; page horizontal overflow was0.

The named container queries use the page's content-box width, not the browser width. The 240px query corresponds to page C<=352 with frozen padding. It reflows the heading without reducing icons, font or padding. Arbitrarily tiny pages below the tested C=240 remain outside this verification.

## Limits

Full application navigation and live backend integration were not validated. The existing MainLayout references useGetBsConfig without importing it, and no local backend configuration is available. Reference slot389 comes from the approved design; existing Web slot240 is a separate geometry test. Neither is claimed as an actual expanded/collapsed host measurement. Real host scrollbar, embedded shell sizing and Sidebar transitions still need integration verification when that environment is available.

Production modifications for this pass are limited to KnowledgeHomeNext.module.css and keyboard Tab visibility in KnowledgeHomePage.tsx. Sidebar, global tokens, shared component styles, other pages and backend APIs are unchanged by this pass.

## Historical v1.2 fluid-minimum validation (superseded by v1.3)

The fixed440 minimum was too restrictive for the user's1455px window. The effective minimum now clamps (grid width minus two gaps)/3 between340 and440. This targets three columns in the compact desktop range without changing Gap40, page Padding56 or the four-column threshold. It depends only on the page content container, not navigation state.

- Outer1455, navigation slot240: C1215, W1103, three341px cards, overflow0.
- C831/W719: one column; C832/W720: two340px columns.
- C1211/W1099: two529.5px columns; C1212/W1100: three340px columns.
- C1512/W1400: three440px columns.
- Original reference outer1920/slot389: W1419, three446.33px columns.
- C1920/W1808: three576px columns.
- C1991/W1879: three599.67px columns; C1992/W1880: four440px columns.

All above points were browser-measured with no page horizontal overflow. The left slot remains a geometry fixture; it is not a measurement of the production host's collapsed Sidebar.

## Historical v1.3 compact-gap validation (superseded by v1.4)

User requested Gap24–36 and wider compact cards. Implemented stable inline/block Gap24, compact minimum350, regular minimum440, with page inline Padding56 unchanged. Effective minimum is clamp(350, (W-48)/3, 440).

Browser measurements:
- Outer1455/slot240: C1215, W1103, three351.664px cards, Gap24, overflow0.
- C835/W723: one723px card; C836/W724: two350px tracks.
- C1209/W1097: two536.5px tracks; C1210/W1098: three350px tracks.
- Outer1920/slot389: W1419, three457px tracks.
- C1943/W1831: three594.33px tracks; C1944/W1832: four440px tracks.
- All boundary measurements and long text at outer1455/slot240 had zero page horizontal overflow. The preview remains a fixture harness, not live host integration.

## Current v1.4 page-padding validation

User explicitly requested page inline Padding40 with card Gap24 unchanged. Compact/regular minimum widths remain350/440. Grid width is now C-80 (excluding any occupied scrollbar width).

Browser measurements:
- Outer1455/slot240: C1215, W1135, three362.33px cards, Gap24, Padding40, overflow0.
- C1177/W1097: two536.5px columns; C1178/W1098: three350px columns.
- Outer1920/slot389: W1451, three467.67px columns.
- C1911/W1831: three594.33px columns; C1912/W1832: four440px columns.
- Long text at outer1455/slot240 had zero horizontal page overflow. No production Sidebar or backend changes.

## v1.5 interaction validation

Browser-verified: create hover opacity=.6; more open opacity=.6 and restored1 after close/mouse-out; unpinned base layer0/hover layer1 while hovered. Sort arrow12x8; open border#333; update-time selection persists after close; closed/mouse-out border#D0D5DE; outline-style none and box-shadow none. ArrowDown/Escape opens/closes the list and restores focus. No backend permissions were fabricated. Geometry remains Padding40/Gap24/compact350-regular440.

## v1.6 Chinese fixtures and discovery hover

Card fixture strings now live in `fixtures.zh-CN.json`; they are preview-only, not production data. Browser checked seven Chinese titles, Chinese descriptions/owners and zero horizontal overflow at outer1455/slot240. Knowledge Square hover measured rgba(51,51,51,.6) border, white background, #333 text and overall opacity1. Web dark mode remains unimplemented; separate Figma dark proposals are linked from the design spec.

## v1.7 five-percent fill checks

Browser verified Knowledge Square hover fill rgba(51,51,51,.05), unchanged#333 border, opacity1. Sort open fill rgba(51,51,51,.05), unchanged#D0D5DE border and8x4 arrow. After selection and mouse-out, white fill, default border, outline none and shadow none. Dark Figma previews remain unchanged.

## v1.8 card-only pinning

Card pin buttons now mutate a local fixture-only Set of pinned IDs, so both pin and unpin can be previewed without backend writes. The first-card checkbox shares this same state. Production still uses the existing pin hook and its real quota/rollback behavior.

More no longer contains Pin, Unpin, Settings or Leave. Final integrated actions are Rename and Delete; Rename is deferred, Delete remains permission-gated. The fixture supplies no privileged permissions, so More currently shows a disabled localized no-actions item. Browser verified false-to-true-to-false pin state and the menu content.

## v1.9 pin FIFO and layout motion

Pinned cards now use session FIFO independently of normal sorting. Unpin restores the selected normal order; re-pin appends to the pinned group. The existing API lacks pin timestamp/order, so initial pins retain first-seen order; reload/multi-device chronology needs an API field. No backend changes.

Framer Motion position-only layout transitions take360ms; followers stagger20ms up to120ms. ID-order layoutDependency prevents resize animation. Reduced-motion disables movement (implemented, OS preference not toggled in browser). CSS Grid still owns all positions.

Browser verified pin Project then Customer, switch to Name (same pin order), unpin Project (normal order restored), re-pin Project (Customer then Project). Observed translate-only matrices during movement and none after settling; three columns approx362.33px at outer1455/slot240, Gap24. Preview uses fixtures only.20 tests, targeted ESLint and production build pass; full typecheck retains pre-existing MainLayout useGetBsConfig error.

## v1.10 newest pin first

Supersedes v1.9 FIFO: each new pin or re-pin leads the pinned group. Unpin restores normal sorting. Updated interaction test verifies newest-first order across sort changes and re-pin. API timestamp limitation is unchanged.

## v1.14 sort overflow

Long content also supplies long sort labels for visual QA. Trigger128x36, normal menu120px, capped menu200px; clipped options show shared Tooltip on hover/focus. Production options and API sorting values are unchanged.
