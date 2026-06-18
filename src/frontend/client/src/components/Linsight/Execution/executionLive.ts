/**
 * ExecutionLiveContext — whether the surrounding execution turn is still live
 * (session status === Running).
 *
 * Why this exists: a group's "running" is derived from per-step `running`, which
 * stays true until a `status:'end'` frame arrives. A safety-blocked / skipped
 * subagent step never gets that end frame, so its group would otherwise show a
 * stuck "正在派出…（已用 N 秒）…" with a forever-ticking clock long after the whole
 * task finished. Only the carrier (ExecutionFlow / TaskTurnPanel / a historical
 * ConversationRound) knows the turn-level status, so it provides this flag and
 * the timeline groups gate their effective running on it: a non-live turn means
 * NOTHING is actually running, regardless of dangling step frames.
 *
 * Default = true so an unwrapped render preserves the raw step.running behavior.
 */
import { createContext, useContext } from 'react';

export const ExecutionLiveContext = createContext(true);

/** True while the surrounding execution turn is still live (status Running). */
export const useExecutionLive = (): boolean => useContext(ExecutionLiveContext);
