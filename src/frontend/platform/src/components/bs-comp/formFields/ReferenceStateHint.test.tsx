import { render } from '@testing-library/react';
import { createInstance } from 'i18next';
import { I18nextProvider } from 'react-i18next';
import { expect, it, vi } from 'vitest';
import type { ReferenceSlotState } from '@/types/assistant';
import en from '../../../../public/locales/en-US/bs.json';
import zh from '../../../../public/locales/zh-Hans/bs.json';
import ja from '../../../../public/locales/ja/bs.json';
import { ReferenceStateHint } from './ReferenceStateHint';

vi.unmock('react-i18next');

it.each([
    ['en', en], ['zh-Hans', zh], ['ja', ja],
] as const)('renders every invalid saved-reference state in %s', async (language, catalog) => {
    const i18n = createInstance();
    await i18n.init({ lng: language, defaultNS: 'bs', resources: { [language]: { bs: catalog } } });
    const states: ReferenceSlotState[] = ['invalid_missing', 'invalid_scope', 'invalid_deleted', 'invalid_legacy', 'deleting', 'valid'].map((state, index) => ({
        slot_key: 'knowledge_list', target_type: 'knowledge_space', target_id: String(4402 + index),
        state: state as ReferenceSlotState['state'], is_valid: false,
    }));
    const { getByRole } = render(<I18nextProvider i18n={i18n}><ReferenceStateHint states={states} /></I18nextProvider>);
    const hint = getByRole('status');
    for (const row of states) {
        const key = row.state === 'valid' ? 'unavailable' : row.state;
        expect(hint.textContent).toContain(`${row.target_id}: ${catalog.references[key]}`);
    }
    expect(hint.textContent).not.toContain('references.');
});
