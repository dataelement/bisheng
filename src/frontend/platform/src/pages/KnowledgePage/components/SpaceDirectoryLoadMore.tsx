import { LoadingState } from "@/components/bs-icons/loading/LoadingState";
import { Button } from "@bisheng/ui";
import type { UseInfiniteQueryResult } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { CursorPage, KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";

interface SpaceDirectoryLoadMoreProps {
  directory: UseInfiniteQueryResult<CursorPage<KnowledgeSpaceChild>>;
  isCurrent: () => boolean;
}

export function SpaceDirectoryLoadMore({ directory, isCurrent }: SpaceDirectoryLoadMoreProps) {
  const { t } = useTranslation("knowledge");
  const sentinelRef = useRef<HTMLDivElement>(null);
  const [nextPageError, setNextPageError] = useState<unknown>(null);
  const { data, error, fetchNextPage, isFetching, isFetchingNextPage, refetch } = directory;
  const pageCount = data?.pages.length;

  const handleLoadNextPage = useCallback(async () => {
    if (isFetching || !isCurrent()) return;
    const result = await fetchNextPage({ cancelRefetch: false });
    if (isCurrent()) setNextPageError(result.error);
  }, [fetchNextPage, isCurrent, isFetching]);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel || !pageCount || isFetching || error || typeof IntersectionObserver === "undefined") return;

    // Reobserve after every page, including an empty page with a continuation cursor.
    let active = true;
    const observer = new IntersectionObserver((entries) => {
      if (active && entries.some((entry) => entry.isIntersecting)) void handleLoadNextPage();
    }, { root: sentinel.parentElement, rootMargin: "0px 0px 240px 0px" });
    observer.observe(sentinel);
    return () => {
      active = false;
      observer.disconnect();
    };
  }, [error, handleLoadNextPage, isFetching, pageCount]);

  return (
    <div ref={sentinelRef} className="flex h-10 w-full shrink-0 items-center justify-center text-caption text-text-3">
      {isFetchingNextPage ? (
        <LoadingState size="inline" label={t("f118.loading_directory")} />
      ) : error ? (
        <Button
          type="button"
          variant="text"
          color="default"
          disabled={isFetching}
          onClick={() => {
            if (error === nextPageError) void handleLoadNextPage();
            else void refetch();
          }}
        >
          {t("retry")}
        </Button>
      ) : null}
    </div>
  );
}
