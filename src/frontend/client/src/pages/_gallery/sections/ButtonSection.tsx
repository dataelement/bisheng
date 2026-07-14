/**
 * Button gallery — DEV-ONLY.
 * Button.tsx is already cva-based; it serves as the reference pattern for how other
 * components should expose variants/sizes. See docs-ui-refactor/01-设计规范.md.
 */
import { Button } from '~/components/ui/Button';
import { ComponentPage, ExampleGroup, ExampleGrid, ExampleCard } from '../components/kit';

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
    <ComponentPage
      title="Button 按钮"
      eng="Button"
      description={
        <>
          已是 <code>cva</code> 变体写法，作为其它组件"留改动余地"的范本：预设档位 +
          允许 <code>className</code> 覆盖。
        </>
      }
      whenToUse={[
        <>主操作用 <code>default</code>（已跟随蓝⇄绿主题）；危险操作用 <code>destructive</code>。</>,
        <>次要操作用 <code>outline</code> / <code>secondary</code>；弱操作用 <code>ghost</code> / <code>link</code>。</>,
        <>尺寸只用 <code>sm / default / lg / icon</code> 四档，不要手写高度/内边距。</>,
        <>特殊一次性样式用 <code>className</code> 覆盖，不要新增变体。</>,
      ]}
    >
      <ExampleGroup title="变体 variant" subtitle="每格含常态与 disabled 态">
        <ExampleGrid cols={4}>
          {VARIANTS.map((v) => (
            <ExampleCard key={v} title={`variant="${v}"`}>
              <Button variant={v}>{v}</Button>
              <Button variant={v} disabled>
                disabled
              </Button>
            </ExampleCard>
          ))}
        </ExampleGrid>
      </ExampleGroup>

      <ExampleGroup title="尺寸 size">
        <ExampleGrid cols={4}>
          {SIZES.map((s) => (
            <ExampleCard key={s} title={`size="${s}"`}>
              <Button size={s}>{s === 'icon' ? '★' : s}</Button>
            </ExampleCard>
          ))}
        </ExampleGrid>
      </ExampleGroup>
    </ComponentPage>
  );
}
