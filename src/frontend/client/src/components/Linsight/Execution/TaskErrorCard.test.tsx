/**
 * TaskErrorCard — friendly rate-limit copy (限流文案统一).
 *
 * Verifies the user-visible contract of the rate-limit copy change:
 *  - desc renders the unified "当前使用人数较多，请稍后再试。" in all three locales;
 *  - the suggestion (hint) line is removed — the empty i18n value is hidden by the
 *    component's `{hint && ...}` guard;
 *  - the title is retained;
 *  - quota_exhausted is left untouched (the throttling-vs-billing split) and still
 *    shows the "contact admin to top up" hint.
 *
 * Uses the REAL i18n resources (not the usual identity mock) so the key→copy
 * wiring and the empty-string-hides-hint behaviour are actually exercised.
 */
import { render, screen } from '@testing-library/react';
import i18n from '~/locales/i18n';
import { TaskErrorCard } from './TaskErrorCard';

// useLocalize → real i18n.t so rendered text is the actual localized copy.
jest.mock('~/hooks', () => {
    const realI18n = require('~/locales/i18n').default;
    return {
        __esModule: true,
        useLocalize: () => (key: string, opts?: any) => realI18n.t(key, opts),
    };
});

const RATE_LIMIT_DESC: Record<string, string> = {
    'zh-Hans': '当前使用人数较多，请稍后再试。',
    en: 'Too many users at the moment. Please try again later.',
    ja: '現在ご利用が集中しています。しばらくしてからもう一度お試しください。',
};

describe('TaskErrorCard — rate-limit friendly copy', () => {
    afterAll(async () => {
        await i18n.changeLanguage('en');
    });

    it.each(Object.entries(RATE_LIMIT_DESC))('renders the unified rate-limit desc in %s', async (lang, expected) => {
        await i18n.changeLanguage(lang);
        render(<TaskErrorCard errorType="rate_limit" detail="raw provider 429 text" />);
        expect(screen.getByText(expected)).toBeInTheDocument();
    });

    it('retains the rate-limit title', async () => {
        await i18n.changeLanguage('zh-Hans');
        render(<TaskErrorCard errorType="rate_limit" />);
        expect(screen.getByText('模型服务繁忙')).toBeInTheDocument();
    });

    it('drops the suggestion line for rate_limit (empty hint hidden)', async () => {
        await i18n.changeLanguage('zh-Hans');
        render(<TaskErrorCard errorType="rate_limit" />);
        // the old suggestion copy must be gone ...
        expect(screen.queryByText(/稍等片刻后重新发起任务/)).not.toBeInTheDocument();
        // ... and the empty hint key must not leak as raw text either
        expect(screen.queryByText('com_linsight_error_hint_rate_limit')).not.toBeInTheDocument();
    });

    it('keeps quota_exhausted distinct (top-up hint intact, split not broken)', async () => {
        await i18n.changeLanguage('zh-Hans');
        render(<TaskErrorCard errorType="quota_exhausted" />);
        expect(screen.getByText('模型服务额度已用尽')).toBeInTheDocument();
        expect(screen.getByText(/联系管理员充值/)).toBeInTheDocument();
    });
});
