import { renderToStaticMarkup } from 'react-dom/server';
import { AdvisorOpening } from './AdvisorLanding';
import mockZh from '../../locales/zh-Hans/translation.json';

jest.mock('~/hooks', () => ({ useLocalize: () => (key: string, options?: Record<string, unknown>) => {
  const value = key.split('.').reduce<unknown>((node, part) => node && typeof node === 'object' ? (node as Record<string, unknown>)[part] : undefined, mockZh);
  return typeof value === 'string' ? value.replace(/{{([^}]+)}}/g, (_, name: string) => String(options?.[name] ?? '')) : value;
} }));
jest.mock('react-router-dom', () => ({ Link: ({ to, children }: { to: string; children: React.ReactNode }) => <a href={to}>{children}</a> }));

test('sent order introduction stays generic across order changes and has one return link without draft tasks', () => {
  const render = (orderNumber: string) => renderToStaticMarkup(<AdvisorOpening scene="orders" compact ready error={false} onRetry={jest.fn()} orderNumber={orderNumber} />);
  const first = render('SYNTHETIC-ORDER-A');
  expect(first).toEqual(render('SYNTHETIC-ORDER-B'));
  expect(first).toContain('assistant-opening-history');
  expect(first).toContain(mockZh.zhgyl.scenes.orders.paragraphs[0]);
  expect(first).not.toContain('SYNTHETIC-ORDER');
  expect(first).not.toContain('assistant-friendly-tasks');
  expect(first.match(/<a /g)).toHaveLength(1);
  expect(first).toContain('href="/c/new?module=order-tracking"');
});
