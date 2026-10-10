/**
 * Input has moved to the shared component library (@bisheng/ui) — spec:
 * 组件-Input输入框.md (32px medium default, gray focus chain, className lands on
 * the SHELL, `inputClassName` on the <input>). This re-export keeps every
 * existing `~/components/ui/Input` / barrel call site working unchanged.
 * New code may import from '@bisheng/ui' directly.
 */
export { Input, SearchInput, PasswordInput } from '@bisheng/ui';
export type { InputProps, SearchInputProps, PasswordInputProps } from '@bisheng/ui';
