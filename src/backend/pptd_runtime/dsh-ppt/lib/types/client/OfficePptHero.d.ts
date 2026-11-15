/** DSH PPT template chooser integrated into the blank-session composer. */
import type { SessionId } from '@deepseek-ai/dsh-client-runtime/client';
import type { InjectFace, PropsLocale, PropsRuntime } from '@deepseek-ai/dsh-client-ui-slots';
import { type OfficeTemplate } from '../protocol.ts';
import type { OfficePptClient } from './rpc.ts';
interface HeroState {
    readonly activeMode: 'ppt' | null;
    readonly loading: boolean;
    readonly templates: readonly OfficeTemplate[];
    readonly selectedId: string | null;
    readonly error: string;
}
/** Session-keyed presentation state shared by the action tray and composer accessory. */
export declare class OfficePptHeroStore {
    private readonly states;
    private readonly listeners;
    snapshot(sessionId: SessionId): HeroState;
    subscribe(sessionId: SessionId, listener: () => void): () => void;
    setMode(sessionId: SessionId, activeMode: HeroState['activeMode']): void;
    setLoading(sessionId: SessionId, loading: boolean): void;
    setError(sessionId: SessionId, error: string): void;
    setTemplates(sessionId: SessionId, templates: readonly OfficeTemplate[]): void;
    select(sessionId: SessionId, template: OfficeTemplate, activeMode: Exclude<HeroState['activeMode'], null>): void;
    deselect(sessionId: SessionId, activeMode: Exclude<HeroState['activeMode'], null>): void;
    private update;
}
/** Faces supplied by the package registration. */
export interface OfficePptHeroInjected {
    readonly client: OfficePptClient;
    readonly mode: OfficePptHeroStore;
}
/** Compact selected-template thumbnail inside the resident input card. */
export declare function OfficePptInputAccessory({ client, mode, sessionId, t, }: PropsRuntime<'conversation.hero.inputAccessory'> & OfficePptHeroInjected & PropsLocale<'dsh-ppt'>): import("react").JSX.Element | null;
/** Selected-template reference shown only while the standard Session is blank. */
export declare function OfficePptStandardInputAccessory(props: PropsRuntime<'conversation.input.accessory'> & OfficePptHeroInjected & PropsLocale<'dsh-ppt'>): import("react").JSX.Element | null;
/** Legacy chooser that expands below the Composer without moving its initial position. */
export declare function OfficePptHeroActions(props: PropsRuntime<'conversation.hero.actions'> & InjectFace<OfficePptHeroInjected> & PropsLocale<'dsh-ppt'>): import("react").JSX.Element;
/** Standard Composer chooser rendered in normal flow below the resident input card. */
export declare function OfficePptStandardComposerDock(props: PropsRuntime<'conversation.composer.dock'> & InjectFace<OfficePptHeroInjected> & PropsLocale<'dsh-ppt'>): import("react").JSX.Element | null;
/** PPT mode control beside the blank-session agent preset. */
export declare function OfficePptStandardModeAction(props: PropsRuntime<'conversation.hero.modeActions'> & InjectFace<OfficePptHeroInjected> & PropsLocale<'dsh-ppt'>): import("react").JSX.Element | null;
export {};