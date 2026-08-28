// @bisheng/ui public API — presentation-only components + design-system utils.
// Contract (README): no state management, no HTTP, no i18n keys, no routing.
export { default as cn } from './utils/cn';
export { Button, buttonVariants } from './components/Button/Button';
export type { ButtonProps, ButtonStyleProps } from './components/Button/Button';
// Toast — imperative `toast.*` API + the single <Toaster /> container
// (组件-Toast轻提示.md). Copy comes from the caller, so the contract holds.
export * from './components/Toast';
// Crash screen. Shared because the identifiers, the QR payload and the log file
// have to be identical across the apps for a support handover to work — the
// copy and the artwork are passed in, so the contract above still holds.
export * from './components/ErrorPage';
// Empty-state / status illustrations. Inline SVG driven by the --illus-* palette
// (blue ⇄ green + grey draft) — artwork only, so the contract above holds.
export * from './components/Illustration';
// Modal — the centered interrupting overlay (组件-Modal弹窗.md). Sizes, mask,
// z-tier, motion and the three exits are baked in; every string is a prop.
export * from './components/Modal';
// Input family — one shell for every single-line field plus the multi-line one
// (组件-Input输入框.md). Sizes, the gray focus chain, the four states and the
// touch rules are baked in; every string (placeholder, a11y labels) is a prop.
export * from './components/Input';
// State page shell — illustration + copy + buttons for an area with no normal
// content (组件-State状态页.md). Every string comes from the caller.
export * from './components/StateView';
// Tooltip — one line of plain text explaining a control
// (组件-Tooltip文字提示.md). The dark surface, the 100ms delay with its skip
// window, the disabled-trigger hot zone and the top overlay tier are baked in;
// the copy is a prop. `TooltipProvider` is optional (app root, shared skip).
export * from './components/Tooltip';
// Selection family — Checkbox (pick several, travels with the form), Radio
// (pick one from a visible set) and Switch (standalone setting, applies
// immediately) per 组件-Checkbox复选框.md §1's分工判定表. Sizes, the gray→brand
// state chain, the card shells and the touch rules are baked in; every string
// is a prop.
export * from './components/Checkbox';
export * from './components/Radio';
export * from './components/Switch';
// Tabs — peer content blocks in one area, switching changes WHERE you are
// (组件-Tabs标签页.md). Line type only; the brand indicator slide, the
// overflow fade + keep-visible scroll and the touch rules are baked in; every
// label is a prop. Same content shown a different WAY is the Segmented below
// (判别表 in 组件-Segmented分段控制器.md §1).
export * from './components/Tabs';
// Segmented — the same content shown a different way, applied immediately
// (组件-Segmented分段控制器.md). The gray track + sliding thumb, equal-width
// segments and the touch rules are baked in; every label is a prop.
export * from './components/Segmented';
// Badge — 「is there anything new」 and 「how many」, in four forms: the corner
// count, the corner dot, the standalone number after a label, and the inline
// status dot (组件-Badge徽标.md). One 16px size, the two semantic colors, the
// no-99+ rule and「0 shows nothing」are baked in; it is never clickable — the
// host is. What says「what this is」is the Tag below (判别表 in Badge §1).
export * from './components/Badge';
// Tag — one word stuck on an object: what it is, what state it is in
// (组件-Tag标签.md). Light tint + dark text only, the five semantic colors plus
// the two frozen exceptions (审批中 blue / 技能 purple), display / closable /
// checkable; a display tag deliberately has no hover, since it is not a button.
export * from './components/Tag';
// Breadcrumb — where the current page sits in the structure
// (组件-Breadcrumb面包屑.md). The collapse rules, the 96px name cap and the
// ellipsis menu are baked in; the page passes the full chain and the copy.
export * from './components/Breadcrumb';
