import { resolveUserAvatarUrl } from '@bisheng/identity';
import type { TUser } from '~/types/chat';

interface MessageAuthorFields {
  user_id?: unknown;
  user_name?: unknown;
  user_avatar?: unknown;
}

export function resolveChatAuthor(
  message: MessageAuthorFields,
  privateViewer?: Pick<TUser, 'id' | 'username' | 'avatar'>,
) {
  const { user_id: id, user_name: name, user_avatar: avatar } = message;
  const authorName = typeof name === 'string' ? name : undefined;
  const isViewer = privateViewer && (
    id == null
      ? !authorName?.trim()
      : (typeof id === 'number' || typeof id === 'string') && String(id) === String(privateViewer.id)
  );

  return isViewer
    ? { name: privateViewer.username || authorName, avatar: resolveUserAvatarUrl(privateViewer.avatar, __APP_ENV__.BASE_URL) }
    : {
        name: authorName,
        avatar: resolveUserAvatarUrl(typeof avatar === 'string' ? avatar : undefined, __APP_ENV__.BASE_URL),
      };
}
