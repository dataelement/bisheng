import type { ChatMessageType } from '~/@types/chat';

type AppMessage = Pick<ChatMessageType, 'category' | 'end' | 'stopped' | 'remark'> & {
    is_bot?: boolean | number;
    interrupted?: boolean;
    id?: string | number;
};

export function isAppMessageStopped(message: Pick<AppMessage, 'stopped' | 'remark'>): boolean {
    return message.stopped === true || message.remark === 'break_answer';
}

export function stopAppMessages<T extends AppMessage>(messages: T[]): T[] {
    let questionIndex = -1;
    messages.forEach((message, index) => { if (message.category === 'question') questionIndex = index; });
    return messages.map((message, index) =>
        index > questionIndex && message.is_bot && message.end === false
            ? { ...message, end: true, stopped: true,
                ...(['tool', 'flow', 'knowledge'].includes(message.category ?? '') ? { interrupted: true } : {}) }
            : message,
    );
}

interface TerminalFrame {
    category?: string;
    type?: string;
    message_id?: string | number;
    message?: unknown;
}

export function finishStoppedAppMessage<T extends AppMessage>(messages: T[], frame: TerminalFrame): T[] {
    if (frame.type !== 'end' || frame.message_id == null
        || ['tool', 'flow', 'knowledge', 'reasoning_answer'].includes(frame.category ?? '')) return messages;
    const payload = frame.message;
    const streamId = payload && typeof payload === 'object' && 'unique_id' in payload && 'output_key' in payload
        ? String(payload.unique_id) + String(payload.output_key)
        : undefined;
    let index = -1;
    messages.forEach((message, i) => {
        if (message.category === 'question') index = -1;
        if (isAppMessageStopped(message)
            && (streamId ? message.id === streamId : ['answer', 'stream_msg'].includes(message.category ?? ''))) index = i;
    });
    return messages.map((message, i) => i === index ? { ...message, id: frame.message_id } : message);
}
