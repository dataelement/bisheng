import React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import {
    Pagination,
    PaginationContent,
    PaginationEllipsis,
    PaginationItem,
    PaginationLink,
} from "~/components/ui/Pagination";
import { useLocalize, usePrefersMobileLayout } from "~/hooks";

interface PaginationBarProps {
    currentPage: number;
    pageSize: number;
    total: number;
    onPageChange: (page: number) => void;
}

/** Reusable pagination footer for file lists */
export function PaginationBar({ currentPage, pageSize, total, onPageChange }: PaginationBarProps) {
    const localize = useLocalize();
    const isH5 = usePrefersMobileLayout();
    const totalPages = Math.max(1, Math.ceil(total / pageSize));

    const getPageNumbers = (): (number | "ellipsis")[] => {
        const pages: (number | "ellipsis")[] = [];
        if (totalPages <= 5) {
            for (let i = 1; i <= totalPages; i++) {
                pages.push(i);
            }
        } else {
            if (currentPage <= 3) {
                pages.push(1, 2, 3, 4, "ellipsis", totalPages);
            } else if (currentPage >= totalPages - 2) {
                pages.push(1, "ellipsis", totalPages - 3, totalPages - 2, totalPages - 1, totalPages);
            } else {
                pages.push(1, "ellipsis", currentPage - 1, currentPage, currentPage + 1, "ellipsis", totalPages);
            }
        }
        return pages;
    };

    if (isH5) {
        return (
            <div className="ml-auto flex min-w-0 items-center justify-end gap-3 whitespace-nowrap text-[12px] text-[#4e5969]">
                <div className="shrink-0">
                    {localize("com_knowledge.total_prefix")}{" "}
                    <span className="text-[#165dff]">{total}</span> {localize("com_knowledge.items_comma")}
                    {localize("com_knowledge.per_page")} {pageSize} {localize("com_knowledge.items_suffix")}
                </div>
                <Pagination className="mx-0 w-auto shrink-0">
                    <PaginationContent>
                        <PaginationItem>
                            <PaginationLink
                                href="#"
                                size="icon"
                                className={"h-6 w-6 " + (currentPage === 1 ? "pointer-events-none opacity-50" : "")}
                                onClick={(e) => {
                                    e.preventDefault();
                                    if (currentPage > 1) onPageChange(currentPage - 1);
                                }}
                            >
                                <ChevronLeft className="size-4" />
                            </PaginationLink>
                        </PaginationItem>
                        <PaginationItem>
                            <span className="px-2 text-[12px] text-[#4e5969]">
                                {currentPage}/{totalPages}
                            </span>
                        </PaginationItem>
                        <PaginationItem>
                            <PaginationLink
                                href="#"
                                size="icon"
                                className={"h-6 w-6 " + (currentPage === totalPages ? "pointer-events-none opacity-50" : "")}
                                onClick={(e) => {
                                    e.preventDefault();
                                    if (currentPage < totalPages) onPageChange(currentPage + 1);
                                }}
                            >
                                <ChevronRight className="size-4" />
                            </PaginationLink>
                        </PaginationItem>
                    </PaginationContent>
                </Pagination>
            </div>
        );
    }

    return (
        <div className="flex items-center gap-4 text-[14px] text-[#4e5969]">
            <div className="flex items-center gap-1">
                <span>
                    {localize("com_knowledge.total_prefix")}{" "}
                    <span className="text-[#165dff]">{total}</span> {localize("com_knowledge.items_comma")}
                </span>
                <span>
                    {localize("com_knowledge.per_page")} {pageSize} {localize("com_knowledge.items_suffix")}
                </span>
            </div>
            <Pagination className="mx-0 w-auto">
                <PaginationContent>
                    <PaginationItem>
                        <PaginationLink
                            href="#"
                            size="icon"
                            className={"w-6 h-6 " + (currentPage === 1 ? "pointer-events-none opacity-50" : "")}
                            onClick={(e) => {
                                e.preventDefault();
                                if (currentPage > 1) onPageChange(currentPage - 1);
                            }}
                        >
                            <ChevronLeft className="size-4" />
                        </PaginationLink>
                    </PaginationItem>
                    {getPageNumbers().map((pageNum, idx) => (
                        <PaginationItem key={idx}>
                            {pageNum === "ellipsis" ? (
                                <PaginationEllipsis />
                            ) : (
                                <PaginationLink
                                    href="#"
                                    isActive={pageNum === currentPage}
                                    className={"w-6 h-6 " + (pageNum === currentPage ? "border-primary text-primary" : "")}
                                    onClick={(e) => {
                                        e.preventDefault();
                                        onPageChange(pageNum as number);
                                    }}
                                >
                                    {pageNum}
                                </PaginationLink>
                            )}
                        </PaginationItem>
                    ))}
                    <PaginationItem>
                        <PaginationLink
                            href="#"
                            size="icon"
                            className={currentPage === totalPages ? "pointer-events-none opacity-50" : ""}
                            onClick={(e) => {
                                e.preventDefault();
                                if (currentPage < totalPages) onPageChange(currentPage + 1);
                            }}
                        >
                            <ChevronRight className="size-4" />
                        </PaginationLink>
                    </PaginationItem>
                </PaginationContent>
            </Pagination>
        </div>
    );
}
