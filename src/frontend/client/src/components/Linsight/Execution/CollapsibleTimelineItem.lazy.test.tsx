/** @jest-environment node */
import { renderToStaticMarkup } from 'react-dom/server';
import CollapsibleTimelineItem from './CollapsibleTimelineItem';

jest.mock('bisheng-icons', () => ({
    Outlined: new Proxy({}, { get: () => () => null }),
}));
jest.mock('~/utils', () => ({ cn: (...parts: unknown[]) => parts.filter(Boolean).join(' ') }));

it('does not mount process bodies behind a collapsed header', () => {
    function HeavyBody(): never { throw new Error('A collapsed tool must not render its body'); }
    const html = renderToStaticMarkup(
        <CollapsibleTimelineItem icon={null} label="Search" open={false} onToggle={() => {}}>
            <HeavyBody />
        </CollapsibleTimelineItem>,
    );
    expect(html).toContain('Search');
});

it('reveals the preserved process body when expanded', () => {
    const html = renderToStaticMarkup(
        <CollapsibleTimelineItem icon={null} label="Search" open onToggle={() => {}}>
            <p>Source output</p>
        </CollapsibleTimelineItem>,
    );
    expect(html).toContain('Source output');
});
