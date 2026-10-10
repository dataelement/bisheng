import * as Dialog from '@radix-ui/react-dialog';

/**
 * Full-screen preview for an attached image. The picture renders at its own
 * size and only shrinks: 60% of the viewport on either axis and at most 640px
 * wide, so a small icon stays small instead of being stretched across the
 * screen and a large one still leaves the conversation visible around it.
 */
export default function DialogImage({ src = '' }: { src?: string }) {
  return (
    <Dialog.Portal>
      <Dialog.Overlay
        className="radix-state-open:animate-show fixed inset-0 z-[100] flex items-center justify-center overflow-hidden bg-black/90 dark:bg-black/80"
        style={{ pointerEvents: 'auto' }}
      >
        <Dialog.Close asChild>
          <button
            className="absolute right-4 top-4 text-gray-50 transition hover:text-gray-200"
            type="button"
          >
            <svg
              stroke="currentColor"
              fill="none"
              strokeWidth="2"
              viewBox="0 0 24 24"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="h-5 w-5"
              height="1em"
              width="1em"
              xmlns="http://www.w3.org/2000/svg"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </Dialog.Close>
        <Dialog.Content
          className="radix-state-open:animate-contentShow relative flex items-center justify-center focus:outline-none"
          tabIndex={-1}
          style={{ pointerEvents: 'auto' }}
        >
          <img
            src={src}
            alt="Uploaded image"
            className="max-h-[60vh] max-w-[min(60vw,640px)] object-contain shadow-xl"
          />
        </Dialog.Content>
      </Dialog.Overlay>
    </Dialog.Portal>
  );
}
