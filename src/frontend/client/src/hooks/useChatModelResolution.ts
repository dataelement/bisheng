/**
 * Per-conversation model resolution.
 *
 * The model picker used to be remembered per USER (`bs:{uid}:chatModel` /
 * `bs:{uid}:taskModel`), so switching the model in conversation A also changed
 * what conversation B showed, and opening a historical conversation displayed
 * whatever was picked last instead of the model that conversation actually ran
 * on. This module narrows the scope to user x mode x conversation.
 *
 * Resolution order (highest first):
 *  1. conversation record  — `bs:{uid}:convModel:{mode}:{convId}`, this user's
 *     explicit pick inside THIS conversation
 *  2. server value         — task conversations only: `linsight_session_version.model`,
 *     the model the last turn really executed with (survives a device switch)
 *  3. user record          — `bs:{uid}:chatModel` / `bs:{uid}:taskModel`, the
 *     last pick anywhere; this is what makes a NEW conversation inherit it
 *  4. admin default        — `chat_default_model_id` / `linsight_default_model_id`
 *  5. positional fallback  — task: first option, daily: last option (pre-existing
 *     behaviour, deliberately unchanged)
 *
 * No Recoil here (the store is frozen): this module owns the computation plus
 * localStorage, and hands the winner back through a callback so the caller keeps
 * writing the existing `chatModel` atom.
 */
import { useCallback, useEffect, useRef } from 'react';

export type ChatModelMode = 'daily' | 'task';

export interface ChatModelOption {
    id: string | number;
    name?: string;
    displayName?: string;
}

/** Which layer won. Everything below `user` is an applied default, not a pick. */
export type ChatModelSource = 'conv' | 'server' | 'user' | 'admin' | 'fallback' | 'none';

type StorableSource = Extract<ChatModelSource, 'conv' | 'user'>;

const conversationKey = (userId: string, mode: ChatModelMode, conversationId: string) =>
    `bs:${userId}:convModel:${mode}:${conversationId}`;

const userKey = (userId: string, mode: ChatModelMode) =>
    `bs:${userId}:${mode === 'task' ? 'taskModel' : 'chatModel'}`;

function readKey(key: string): string | null {
    try {
        return localStorage.getItem(key);
    } catch {
        return null;
    }
}

function writeKey(key: string, value: string): void {
    try {
        localStorage.setItem(key, value);
    } catch { /* private mode / quota — the picker still works, it just won't stick */ }
}

function dropKey(key: string): void {
    try {
        localStorage.removeItem(key);
    } catch { /* ignore */ }
}

export function readConversationModel(
    userId: string,
    mode: ChatModelMode,
    conversationId: string,
): string | null {
    return readKey(conversationKey(userId, mode, conversationId));
}

export function writeConversationModel(
    userId: string,
    mode: ChatModelMode,
    conversationId: string,
    modelId: string | number,
): void {
    writeKey(conversationKey(userId, mode, conversationId), String(modelId));
}

export function readUserModel(userId: string, mode: ChatModelMode): string | null {
    return readKey(userKey(userId, mode));
}

export function writeUserModel(userId: string, mode: ChatModelMode, modelId: string | number): void {
    writeKey(userKey(userId, mode), String(modelId));
}

/**
 * Carry a conversation's records to another id, for both modes.
 *
 * A first turn is composed under the id `new`; the URL is only rewritten to the
 * real id once the backend has assigned one. Without this the pick made while
 * composing would be stranded in the `new` bucket and the freshly created
 * conversation would resolve from the user record instead.
 */
export function moveConversationModel(userId: string, fromId: string, toId: string): void {
    if (fromId === toId) return;
    (['daily', 'task'] as ChatModelMode[]).forEach((mode) => {
        const saved = readKey(conversationKey(userId, mode, fromId));
        if (saved) {
            writeKey(conversationKey(userId, mode, toId), saved);
        }
        dropKey(conversationKey(userId, mode, fromId));
    });
}

/**
 * Pull the admin-configured default out of `/api/v1/llm/workbench`.
 * `linsight_default_model_id` for task mode, `chat_default_model_id` for daily.
 * Absent / null (the admin never set one) yields null, and resolution falls
 * through to the positional default.
 */
export function readAdminDefaultModelId(
    workbenchConfig: unknown,
    mode: ChatModelMode,
): string | null {
    const raw = (workbenchConfig as Record<string, unknown> | undefined)?.[
        mode === 'task' ? 'linsight_default_model_id' : 'chat_default_model_id'
    ];
    return typeof raw === 'string' || typeof raw === 'number' ? String(raw) : null;
}

export interface ResolveChatModelInput {
    models: ChatModelOption[];
    mode: ChatModelMode;
    conversationSavedId?: string | null;
    serverModelId?: string | null;
    userSavedId?: string | null;
    adminDefaultId?: string | null;
}

export interface ResolveChatModelResult {
    target: ChatModelOption | null;
    source: ChatModelSource;
    /** Records that pointed at a model that no longer exists — drop them. */
    staleSources: StorableSource[];
}

const findModel = (models: ChatModelOption[], id: string | number | null | undefined) =>
    id === null || id === undefined || id === ''
        ? undefined
        : models.find((m) => String(m.id) === String(id));

/**
 * Pure resolution — the whole priority chain in one testable function.
 *
 * A stored id that no longer resolves (model removed or disabled by the admin)
 * is reported in `staleSources` so the caller can drop it and let the next layer
 * take over for good, matching the behaviour the per-user memory already had.
 */
export function resolveChatModel({
    models,
    mode,
    conversationSavedId,
    serverModelId,
    userSavedId,
    adminDefaultId,
}: ResolveChatModelInput): ResolveChatModelResult {
    const staleSources: StorableSource[] = [];
    if (!models.length) {
        return { target: null, source: 'none', staleSources };
    }

    const fromConversation = findModel(models, conversationSavedId);
    if (fromConversation) {
        return { target: fromConversation, source: 'conv', staleSources };
    }
    if (conversationSavedId) {
        staleSources.push('conv');
    }

    const fromServer = findModel(models, serverModelId);
    if (fromServer) {
        return { target: fromServer, source: 'server', staleSources };
    }

    const fromUser = findModel(models, userSavedId);
    if (fromUser) {
        return { target: fromUser, source: 'user', staleSources };
    }
    if (userSavedId) {
        staleSources.push('user');
    }

    const fromAdmin = findModel(models, adminDefaultId);
    if (fromAdmin) {
        return { target: fromAdmin, source: 'admin', staleSources };
    }

    // Positional fallback, unchanged: task mode takes the first configured
    // model, daily mode the last one.
    const fallback = mode === 'task' ? models[0] : models[models.length - 1];
    return { target: fallback ?? null, source: 'fallback', staleSources };
}

/** `source` values that represent a deliberate selection rather than a default. */
export const isDeliberateSource = (source: ChatModelSource) =>
    source === 'conv' || source === 'server' || source === 'user';

export interface UseChatModelResolutionParams {
    userId?: string | number | null;
    conversationId: string;
    mode: ChatModelMode;
    models: ChatModelOption[];
    adminDefaultId?: string | null;
    /**
     * Task conversations only: the model the last turn executed with, from
     * `linsight_session_version.model`. It arrives after the first render, so it
     * upgrades an already-applied lower-priority answer (never a conversation
     * record, and never a pick the user just made).
     */
    serverModelId?: string | null;
    /** Blocks resolution while upstream config is still loading. */
    ready?: boolean;
    onResolved: (target: ChatModelOption, deliberate: boolean) => void;
}

export interface UseChatModelResolutionResult {
    /** Persist an explicit pick: this conversation, and the user-level default. */
    persistPick: (modelId: string | number) => void;
}

/**
 * Resolves once per (conversation, mode) and applies the answer through
 * `onResolved`. Later renders don't re-apply it, so a user's pick is never
 * clobbered by a re-run — the one exception is a late `serverModelId`, which
 * upgrades a result that came from a layer below it.
 */
export function useChatModelResolution({
    userId,
    conversationId,
    mode,
    models,
    adminDefaultId,
    serverModelId,
    ready = true,
    onResolved,
}: UseChatModelResolutionParams): UseChatModelResolutionResult {
    // What is CURRENTLY applied: which (conversation, mode) it belongs to, and
    // which layer it came from. Deliberately not a per-key map — the caller owns
    // a single shared value, so coming back to a conversation must re-apply that
    // conversation's model rather than leave the previous one on screen.
    const appliedRef = useRef<{ key: string; source: ChatModelSource } | null>(null);
    const onResolvedRef = useRef(onResolved);
    onResolvedRef.current = onResolved;

    const uid = userId === null || userId === undefined ? '' : String(userId);
    const appliedKey = `${mode}:${conversationId}`;

    useEffect(() => {
        if (!ready || !uid || !models.length) return;

        const applied =
            appliedRef.current?.key === appliedKey ? appliedRef.current.source : undefined;
        // This conversation is already settled and nothing better is available.
        // A late server value still gets to upgrade a lower-priority answer.
        if (applied && (applied === 'conv' || applied === 'server' || !serverModelId)) return;

        const { target, source, staleSources } = resolveChatModel({
            models,
            mode,
            conversationSavedId: readConversationModel(uid, mode, conversationId),
            serverModelId,
            userSavedId: readUserModel(uid, mode),
            adminDefaultId,
        });

        staleSources.forEach((stale) => {
            dropKey(
                stale === 'conv'
                    ? conversationKey(uid, mode, conversationId)
                    : userKey(uid, mode),
            );
        });

        if (!target) return;
        // A late server value that agrees with what is already shown is not a
        // change — record the upgrade but skip the write.
        const alreadyShown = applied !== undefined && applied === source;
        appliedRef.current = { key: appliedKey, source };
        if (alreadyShown) return;
        onResolvedRef.current(target, isDeliberateSource(source));
    }, [ready, uid, appliedKey, conversationId, mode, models, adminDefaultId, serverModelId]);

    const persistPick = useCallback(
        (modelId: string | number) => {
            if (!uid) return;
            writeConversationModel(uid, mode, conversationId, modelId);
            // The user-level record is what a brand-new conversation inherits.
            writeUserModel(uid, mode, modelId);
            // Pin it so the effect above treats this conversation as settled and
            // cannot overwrite the pick with a lower-priority layer.
            appliedRef.current = { key: `${mode}:${conversationId}`, source: 'conv' };
        },
        [uid, mode, conversationId],
    );

    return { persistPick };
}
