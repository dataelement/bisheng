import { act, renderHook } from '@testing-library/react';
import {
    moveConversationModel,
    readAdminDefaultModelId,
    resolveChatModel,
    useChatModelResolution,
    type ChatModelOption,
} from './useChatModelResolution';

// Mirrors the customer-site shape that started this: two models configured, the
// weaker one first in admin order.
const MODELS: ChatModelOption[] = [
    { id: '3', displayName: 'Qwen3-Next-80B-A3B-Instruct' },
    { id: '6', displayName: 'DeepSeek-V4-Flash' },
];

describe('resolveChatModel — priority chain', () => {
    it('prefers the conversation record over everything else', () => {
        const { target, source } = resolveChatModel({
            models: MODELS,
            mode: 'task',
            conversationSavedId: '6',
            serverModelId: '3',
            userSavedId: '3',
            adminDefaultId: '3',
        });
        expect(target?.id).toBe('6');
        expect(source).toBe('conv');
    });

    // The cross-device case: this browser has no record for the conversation, so
    // the model the last turn actually executed with wins over the user's last
    // pick anywhere.
    it('falls back to the server value before the user record', () => {
        const { target, source } = resolveChatModel({
            models: MODELS,
            mode: 'task',
            serverModelId: '3',
            userSavedId: '6',
            adminDefaultId: '6',
        });
        expect(target?.id).toBe('3');
        expect(source).toBe('server');
    });

    // This layer is what makes a brand-new conversation inherit the last pick.
    it('uses the user record when there is no conversation or server value', () => {
        const { target, source } = resolveChatModel({
            models: MODELS,
            mode: 'daily',
            userSavedId: '3',
            adminDefaultId: '6',
        });
        expect(target?.id).toBe('3');
        expect(source).toBe('user');
    });

    it('uses the admin default when nothing was ever picked', () => {
        const { target, source } = resolveChatModel({
            models: MODELS,
            mode: 'daily',
            adminDefaultId: '6',
        });
        expect(target?.id).toBe('6');
        expect(source).toBe('admin');
    });

    // Regression guard for the customer site, where linsight_default_model_id is
    // null: task mode must keep landing on the FIRST configured model and daily
    // mode on the last one — the pre-existing behaviour this change preserves.
    it('falls back positionally per mode when the admin default is unset', () => {
        expect(resolveChatModel({ models: MODELS, mode: 'task' })).toMatchObject({
            target: MODELS[0],
            source: 'fallback',
        });
        expect(resolveChatModel({ models: MODELS, mode: 'daily' })).toMatchObject({
            target: MODELS[1],
            source: 'fallback',
        });
    });

    it('returns nothing when no models are configured', () => {
        expect(resolveChatModel({ models: [], mode: 'daily', userSavedId: '3' })).toEqual({
            target: null,
            source: 'none',
            staleSources: [],
        });
    });
});

describe('resolveChatModel — stale records', () => {
    // A model the admin removed or disabled must not pin the picker forever: the
    // record is reported so the caller drops it and the next layer takes over.
    it('reports an unresolvable conversation record and moves on', () => {
        const { target, source, staleSources } = resolveChatModel({
            models: MODELS,
            mode: 'daily',
            conversationSavedId: '999',
            userSavedId: '6',
        });
        expect(target?.id).toBe('6');
        expect(source).toBe('user');
        expect(staleSources).toEqual(['conv']);
    });

    it('reports both records when neither resolves', () => {
        const { target, source, staleSources } = resolveChatModel({
            models: MODELS,
            mode: 'daily',
            conversationSavedId: '999',
            userSavedId: '998',
            adminDefaultId: '3',
        });
        expect(target?.id).toBe('3');
        expect(source).toBe('admin');
        expect(staleSources).toEqual(['conv', 'user']);
    });

    // An unresolvable SERVER value is not a stored record — nothing to clean up.
    it('never reports the server value as stale', () => {
        const { source, staleSources } = resolveChatModel({
            models: MODELS,
            mode: 'task',
            serverModelId: '999',
            userSavedId: '6',
        });
        expect(source).toBe('user');
        expect(staleSources).toEqual([]);
    });

    it('treats an empty-string id as absent rather than as a lookup', () => {
        const { source } = resolveChatModel({
            models: MODELS,
            mode: 'daily',
            conversationSavedId: '',
            userSavedId: '6',
        });
        expect(source).toBe('user');
    });
});

describe('readAdminDefaultModelId', () => {
    it('reads the per-mode key and stringifies numeric ids', () => {
        const cfg = { linsight_default_model_id: 3, chat_default_model_id: '6' };
        expect(readAdminDefaultModelId(cfg, 'task')).toBe('3');
        expect(readAdminDefaultModelId(cfg, 'daily')).toBe('6');
    });

    // The customer site has linsight_default_model_id: null.
    it('returns null for an unset default or a missing config', () => {
        expect(readAdminDefaultModelId({ linsight_default_model_id: null }, 'task')).toBeNull();
        expect(readAdminDefaultModelId(undefined, 'daily')).toBeNull();
    });
});

describe('useChatModelResolution — applying across conversations', () => {
    const uid = '42';
    const keyFor = (mode: string, convId: string) => `bs:${uid}:convModel:${mode}:${convId}`;

    beforeEach(() => {
        localStorage.clear();
    });

    const renderFor = (conversationId: string, onResolved: jest.Mock) =>
        renderHook(
            ({ convId }: { convId: string }) =>
                useChatModelResolution({
                    userId: uid,
                    conversationId: convId,
                    mode: 'daily',
                    models: MODELS,
                    onResolved,
                }),
            { initialProps: { convId: conversationId } },
        );

    it('applies each conversation its own model when navigating between them', () => {
        localStorage.setItem(keyFor('daily', 'A'), '3');
        localStorage.setItem(keyFor('daily', 'B'), '6');
        const onResolved = jest.fn();

        const { rerender } = renderFor('A', onResolved);
        expect(onResolved).toHaveBeenLastCalledWith(MODELS[0], true);

        rerender({ convId: 'B' });
        expect(onResolved).toHaveBeenLastCalledWith(MODELS[1], true);

        // Regression: the caller holds ONE shared value, so coming back to A has
        // to re-apply A's model instead of leaving B's on screen.
        rerender({ convId: 'A' });
        expect(onResolved).toHaveBeenLastCalledWith(MODELS[0], true);
    });

    it('does not re-apply while staying in the same conversation', () => {
        localStorage.setItem(keyFor('daily', 'A'), '3');
        const onResolved = jest.fn();

        const { rerender } = renderFor('A', onResolved);
        rerender({ convId: 'A' });
        rerender({ convId: 'A' });
        expect(onResolved).toHaveBeenCalledTimes(1);
    });

    it('persistPick records the conversation and the user-level default', () => {
        const onResolved = jest.fn();
        const { result } = renderFor('A', onResolved);

        act(() => result.current.persistPick('6'));

        expect(localStorage.getItem(keyFor('daily', 'A'))).toBe('6');
        // The user-level record is what the next NEW conversation inherits.
        expect(localStorage.getItem(`bs:${uid}:chatModel`)).toBe('6');
    });

    it('moveConversationModel carries a `new` draft onto the real id', () => {
        localStorage.setItem(keyFor('task', 'new'), '3');
        moveConversationModel(uid, 'new', 'real-id');

        expect(localStorage.getItem(keyFor('task', 'real-id'))).toBe('3');
        expect(localStorage.getItem(keyFor('task', 'new'))).toBeNull();
    });
});
