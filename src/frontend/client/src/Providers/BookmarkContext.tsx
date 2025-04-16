import { createContext, useContext } from 'react';
import type { TConversationTag } from '~/data-provider/data-provider/src';

type TBookmarkContext = { bookmarks: TConversationTag[] };

export const BookmarkContext = createContext<TBookmarkContext>({
  bookmarks: [],
} as TBookmarkContext);
export const useBookmarkContext = () => useContext(BookmarkContext);
