import { asRecord, parsePayload, type ChatMessage } from '@bisheng/chat/core';

// F132 long-term memory (AC-09, design R7): the admin log pages never show what a
// memory tool read or wrote. Persisted memory tool events are already redacted to
// {"redacted": true, "op", "item_ids"}; these pages render a fixed placeholder for
// them and never call the /api/v1/memory endpoints.

// The built-in memory tools; a third-party tool that merely starts with "memory_" is not one.
const MEMORY_TOOL_NAMES = new Set(['memory_write', 'memory_search']);
const PAYLOAD_FIELDS = ['input_str', 'input', 'output', 'args', 'results', 'result', 'tool_input', 'tool_output'];

function isRedacted(value: unknown): boolean {
    return asRecord(parsePayload(value)).redacted === true;
}

/** True for a memory tool event: a built-in memory tool name or any redacted payload part. */
export function isMemoryToolEvent(value: unknown): boolean {
    const record = asRecord(parsePayload(value));
    const name = [record.tool_key, record.tool_name, record.name].find(item => typeof item === 'string');
    if (typeof name === 'string' && MEMORY_TOOL_NAMES.has(name)) return true;
    if (record.redacted === true) return true;
    return PAYLOAD_FIELDS.some(field => isRedacted(record[field]));
}

function isMemoryRun(message: ChatMessage): boolean {
    return message.kind === 'run' && message.category !== 'node_run' && isMemoryToolEvent(message.payload);
}

/** Replace every field a run card could display with the placeholder. */
export function maskMemoryRuns(messages: ChatMessage[], placeholder: string): ChatMessage[] {
    return messages.map(message => {
        if (!isMemoryRun(message)) return message;
        const toolKey = asRecord(parsePayload(message.payload)).tool_key;
        return {
            ...message,
            text: placeholder,
            reasoning: '',
            payload: typeof toolKey === 'string' ? { tool_key: toolKey, redacted: true } : { redacted: true },
            raw: { ...message.raw, message: placeholder, thought: placeholder, intermediate_steps: placeholder },
        };
    });
}

/** Run-card title override; undefined leaves the default presentation in place. */
export function memoryRunPresentation(message: ChatMessage, title: string): { title: string; unavailable: boolean } | undefined {
    return isMemoryRun(message) ? { title, unavailable: false } : undefined;
}
