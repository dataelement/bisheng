// @ts-strict-ignore
/**
 * Barrel for the linsight execution-flow helpers.
 *
 * The module was split by concern (it had outgrown the 600-line file cap); this
 * file keeps the original import surface so every call site stays untouched.
 * Pick the concrete module when adding code:
 *   execTypes  — frame / step / node type contracts (start here)
 *   stepTree   — frame merge + flow/timeline grouping
 *   narration  — firstLine + the group narration aside
 *   activity   — tool-call activity buckets
 *   clarify    — user_input parsing / answer composition
 *   taskStatus — status predicates + session pseudo-task split
 */
export * from './execTypes';
export * from './stepTree';
export * from './narration';
export * from './activity';
export * from './clarify';
export * from './taskStatus';
