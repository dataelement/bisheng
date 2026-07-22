// @ts-strict-ignore
/**
 * Button has moved to the shared component library (@bisheng/ui) — the first
 * component managed there and consumed by both apps. This re-export keeps every
 * existing `~/components/ui/Button` call site working unchanged.
 * New code may import from '@bisheng/ui' directly.
 */
export { Button, buttonVariants } from '@bisheng/ui';
export type { ButtonProps, ButtonStyleProps } from '@bisheng/ui';
