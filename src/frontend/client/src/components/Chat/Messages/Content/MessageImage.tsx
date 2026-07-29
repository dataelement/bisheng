import * as Dialog from '@radix-ui/react-dialog';
import { useEffect, useState } from 'react';
import { getAttachmentUrl } from '~/api/chatApi';
import DialogImage from './DialogImage';
import { InvalidImagePlaceholder } from './InvalidImagePlaceholder';

/**
 * An image a user attached to a message: thumbnail, click to view full screen.
 *
 * The link recorded on the message was signed when the file was uploaded and
 * has long since expired on any older conversation, so the link is fetched
 * fresh at render. When that isn't possible — the storage no longer holds the
 * file, or the message predates attachments being kept — the placeholder says
 * so instead of leaving a broken image behind.
 */
export function MessageImage({
  conversationId,
  fileId,
  altText,
}: {
  conversationId?: string;
  fileId?: string;
  altText?: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // A just-sent message reaches here before the backend has assigned the
    // conversation its id. That's "not yet", not "gone" — keep waiting, or the
    // placeholder flashes up on every image the user sends.
    if (!conversationId || !fileId) {
      return;
    }
    setFailed(false);
    getAttachmentUrl(conversationId, fileId).then((fresh) => {
      if (cancelled) {
        return;
      }
      if (fresh) {
        setUrl(fresh);
      } else {
        setFailed(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [conversationId, fileId]);

  // Debug aid: the resolved link and the ids it was resolved from are on the
  // wrapper, so a broken picture can be traced from devtools without digging
  // through React state.
  const debugAttrs = {
    'data-chat-id': conversationId,
    'data-file-id': fileId,
    'data-attachment-url': url ?? undefined,
  };

  if (failed) {
    return <InvalidImagePlaceholder {...debugAttrs} />;
  }

  if (!url) {
    // Same footprint as the thumbnail so the message doesn't jump once it lands.
    return (
      <div
        {...debugAttrs}
        className="h-[120px] w-[160px] animate-pulse rounded-lg bg-fill-2"
      />
    );
  }

  return (
    <Dialog.Root>
      <Dialog.Trigger asChild>
        <img
          {...debugAttrs}
          src={url}
          alt={altText ?? ''}
          onError={() => setFailed(true)}
          className="h-[120px] w-[160px] cursor-pointer rounded-lg object-cover"
        />
      </Dialog.Trigger>
      <DialogImage src={url} />
    </Dialog.Root>
  );
}
