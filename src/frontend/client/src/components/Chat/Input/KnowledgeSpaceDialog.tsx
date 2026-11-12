import { useState } from "react";
import { useVisibleKnowledgeSpaces } from "~/hooks/useVisibleKnowledgeSpaces";
import {
  KnowledgePickerDialog,
  type KnowledgePickerSelectionProps,
} from "./KnowledgePickerDialog";

export function KnowledgeSpaceDialog(props: KnowledgePickerSelectionProps) {
  const [keyword, setKeyword] = useState("");
  const { spaces, isFetching, isError, retry, hasMore, loadMore } =
    useVisibleKnowledgeSpaces({ keyword });
  return (
    <KnowledgePickerDialog
      {...props}
      kind="space"
      keyword={keyword}
      onKeywordChange={setKeyword}
      groups={spaces.length ? [{ key: "visible", items: spaces }] : []}
      isFetching={isFetching}
      isError={isError}
      onRetry={() => {
        void retry();
      }}
      hasMore={hasMore}
      onLoadMore={loadMore}
    />
  );
}
