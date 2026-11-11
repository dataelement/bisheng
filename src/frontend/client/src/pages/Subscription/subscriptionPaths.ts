/** Parse path-based ids together so cached route params cannot select a stale channel. */
export function extractShareChannelIdFromPath(pathname: string): string | undefined {
  return pathname.match(/\/channel\/share\/([^/?#]+)/)?.[1];
}

export function extractDetailChannelIdFromPath(pathname: string): string | undefined {
  return pathname.match(/\/channel\/(?!share\/)([^/?#]+)/)?.[1];
}
