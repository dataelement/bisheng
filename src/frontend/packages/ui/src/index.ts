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
