import type { ChatMessage } from '~/api/chatApi';

export function MessageTime({ message }: { message: ChatMessage }) {
  const value = message.createdAt || message.clientTimestamp;
  if (!value) return null;
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return null;
  return <time className="dsh-message-time" dateTime={date.toISOString()} title={date.toLocaleString()}>
    {date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })}
  </time>;
}
