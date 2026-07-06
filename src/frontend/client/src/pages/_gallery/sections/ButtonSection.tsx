/**
 * Button gallery — DEV-ONLY.
 * Button.tsx is already cva-based; it serves as the reference pattern for how other
 * components should expose variants/sizes. See docs-ui-refactor/01-设计规范.md.
 */
import { Button } from '~/components/ui/Button';
import { Section, Demo, DemoGrid } from '../components/kit';

const VARIANTS = [
  'default',
  'secondary',
  'secondaryBrand',
  'outline',
  'ghost',
  'destructive',
  'submit',
  'link',
] as const;

const SIZES = ['sm', 'default', 'lg', 'icon'] as const;

export function ButtonSection() {
  return (
    <Section
      id="button"
      title="Button 按钮"
      subtitle={
        <>
          已是 <code>cva</code> 变体写法，作为其它组件"留改动余地"的范本：预设档位 + 允许{' '}
          <code>className</code> 覆盖。
        </>
      }
    >
      <DemoGrid cols={4}>
        {VARIANTS.map((v) => (
          <Demo key={v} label={`variant="${v}"`}>
            <Button variant={v}>{v}</Button>
            <Button variant={v} disabled>
              disabled
            </Button>
          </Demo>
        ))}
      </DemoGrid>

      <h3 className="mb-3 mt-8 text-sm font-medium text-text-primary">尺寸 size</h3>
      <DemoGrid cols={4}>
        {SIZES.map((s) => (
          <Demo key={s} label={`size="${s}"`}>
            <Button size={s}>{s === 'icon' ? '★' : s}</Button>
          </Demo>
        ))}
      </DemoGrid>
    </Section>
  );
}
