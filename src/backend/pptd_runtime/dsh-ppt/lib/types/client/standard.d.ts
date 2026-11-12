/** Standard Composer registration shared by cross-version adapter bundles. */
import type { ClientContext, SessionId } from '@deepseek-ai/dsh-client-runtime/client';
import type { OwnerOf } from '@deepseek-ai/dsh-client-ui-slots';
import { type OfficePptHeroInjected } from './OfficePptHero.tsx';
/** Owner props supplied to the standard Composer input accessory slot. */
export type StandardInputZone = OwnerOf<'conversation.composer.dock'>;
declare module '@deepseek-ai/dsh-client-ui-slots' {
    interface SlotMap {
        /** Template reference rail inside the standard Composer card. */
        'conversation.input.accessory': {
            kind: 'list';
            scope: 'session';
            owner: StandardInputZone;
        };
        /** Product mode controls beside the blank-session agent preset. */
        'conversation.hero.modeActions': {
            kind: 'list';
            scope: 'session-maybe';
            owner: StandardInputZone;
        };
    }
}
/** Browser services required by the standard Composer adapter. */
export declare const standardInject: string[];
/** Build the session-scoped browser face shared by both Composer layouts. */
export declare function officePptHeroInjection(ctx: ClientContext): (sessionId: SessionId) => OfficePptHeroInjected;
/**
 * Register the PPT chooser on the cross-version standard Composer seats.
 * @param ctx - Browser context that owns the standard Composer slots.
 */
export declare function applyStandard(ctx: ClientContext): void;