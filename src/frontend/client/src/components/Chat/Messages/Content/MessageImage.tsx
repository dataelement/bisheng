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
  initialUrl,
}: {
  conversationId?: string;
  fileId?: string;
  altText?: string;
  /** Link the client already holds from the upload, if any. */
  initialUrl?: string;
}) {
  // Stored links carry the internal storage host, which the browser can't
  // reach — same swap the download card does.
  const toReachable = (u?: string | null) =>
    u ? u.replace(/https?:\/\/[^/]+/, __APP_ENV__.BASE_URL) : null;

  const [url, setUrl] = useState<string | null>(toReachable(initialUrl));
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // Nothing to ask for, and nothing to show either.
    if (!conversationId || !fileId) {
      if (!initialUrl) {
        return;
      }
      setUrl(toReachable(initialUrl));
      return;
    }
    setFailed(false);
    // The upload link renders straight away — a message the user just sent
    // isn't in the database yet, so asking the backend for a link would come
    // back empty and read as a dead image. The re-issued link replaces it when
    // it arrives, which is what makes an old conversation work.
    getAttachmentUrl(conversationId, fileId).then((fresh) => {
      if (cancelled) {
        return;
      }
      if (fresh) {
        setUrl(toReachable(fresh));
      } else if (!initialUrl) {
        setFailed(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [conversationId, fileId, initialUrl]);

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
        className="h-[100px] w-[100px] animate-pulse rounded-lg bg-fill-1"
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
          // A transparent PNG would otherwise sit on the page's white and lose
          // its own black artwork; the tint gives it something to show against.
          // Deliberately a fixed light gray rather than a neutral token: the
          // artwork inside the file doesn't invert with the theme, so a backdrop
          // that darkened alongside it would hide the very thing it's here for.
          className="h-[100px] w-[100px] cursor-pointer rounded-lg bg-fill-1 object-cover"
        />
      </Dialog.Trigger>
      <DialogImage src={url} />
    </Dialog.Root>
  );
}
