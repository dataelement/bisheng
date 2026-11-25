import { configuredKnowledgeDefaults, splitComposerKnowledge } from './composerKnowledge';

const org = (id: string) => ({ id, name: `kb ${id}`, type: 'org' });

it('keeps every selection visible when nothing is hidden', () => {
    const selected = [org('1'), org('2')];

    expect(splitComposerKnowledge(selected, [{ id: 1, name: 'A' }, { id: 2, name: 'B', show_in_composer: true }])).toEqual({
        visible: selected,
        hidden: [],
    });
    expect(splitComposerKnowledge(selected, undefined).hidden).toEqual([]);
});

it('moves configured knowledge bases hidden from the composer out of the tags', () => {
    const selected = [org('1'), org('2'), org('3')];

    const { visible, hidden } = splitComposerKnowledge(selected, [{ id: 2, name: 'B', show_in_composer: false }]);

    expect(visible.map((kb) => kb.id)).toEqual(['1', '3']);
    expect(hidden.map((kb) => kb.id)).toEqual(['2']);
});

it('matches only org selections, comparing ids as strings', () => {
    const space = { id: '2', name: 'space 2', type: 'space' };

    const { visible, hidden } = splitComposerKnowledge([space, org('2')], [{ id: 2, name: 'B', show_in_composer: false }]);

    expect(visible).toEqual([space]);
    expect(hidden).toEqual([org('2')]);
});

it('preselects every configured knowledge base, shown or not', () => {
    const config = { orgKbs: [{ id: 1, name: 'A' }, { id: 2, name: 'B', show_in_composer: false }] };

    expect(configuredKnowledgeDefaults(config)).toEqual([
        { id: '1', name: 'A', type: 'org' },
        { id: '2', name: 'B', type: 'org' },
    ]);
    expect(configuredKnowledgeDefaults({ ...config, knowledgeBase: { enabled: false } })).toEqual([]);
    expect(configuredKnowledgeDefaults(undefined)).toEqual([]);
});
