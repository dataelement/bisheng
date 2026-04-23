import { useState } from 'react';
import { Pagination, PaginationContent, PaginationItem, PaginationLink, PaginationNext, PaginationPrevious } from './index';
import { Input } from '../input';
import { useTranslation } from 'react-i18next';

interface IProps {
    /** Current page number */
    page: number,
    /** Limit */
    pageSize: number,
    /** Item total */
    total: number,
    /** Maximum number of pages to display at once */
    maxVisiblePages?: number,
    /** Function to handle page change */
    onChange?: (p: number) => void,
    className?: string,
    /** Whether to show jump to page input */
    showJumpInput?: boolean,
    /** Text for "Jump to" label */
    jumpToText?: string,
    /** Text for "page" label */
    pageText?: string,
    /** Whether to show total count */
    showTotal?: boolean
}

const AutoPagination = ({
    page,
    pageSize,
    total,
    maxVisiblePages = 5,
    className,
    onChange,
    showJumpInput = false,
    jumpToText = 'Go to',
    pageText = 'page',
    showTotal = false
}: IProps) => {
    const { t } = useTranslation();
    const totalPages = Math.ceil(total / pageSize);
    const [jumpPage, setJumpPage] = useState<string>("");

    const handlePageChange = (newPage: number) => {
        if (newPage >= 1 && newPage <= totalPages && newPage !== page) {
            onChange?.(newPage);
        }
    };

    const handleJumpPage = () => {
        const pageNum = parseInt(jumpPage, 10);
        if (!isNaN(pageNum) && pageNum >= 1 && pageNum <= totalPages) {
            handlePageChange(pageNum);
        }
    };

    const handleJumpInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        setJumpPage(e.target.value);
    };

    const handleJumpInputBlur = () => {
        handleJumpPage();
    };

    const getPageNumbers = (): (number | "ellipsis")[] => {
        const safeTotalPages = Math.max(1, totalPages);
        const pages: (number | "ellipsis")[] = [];

        if (safeTotalPages <= maxVisiblePages) {
            for (let i = 1; i <= safeTotalPages; i++) pages.push(i);
            return pages;
        }

        if (page <= 3) {
            pages.push(1, 2, 3, 4, "ellipsis", safeTotalPages);
            return pages;
        }

        if (page >= safeTotalPages - 2) {
            pages.push(1, "ellipsis", safeTotalPages - 3, safeTotalPages - 2, safeTotalPages - 1, safeTotalPages);
            return pages;
        }

        pages.push(1, "ellipsis", page - 1, page, page + 1, "ellipsis", safeTotalPages);
        return pages;
    };

    return (
        <Pagination className={className}>
            <PaginationContent>
                {showTotal && (
                    <PaginationItem key="total">
                        <span className="text-sm text-[#86909c] mr-2 whitespace-nowrap">
                            {t('pagination.totalPrefix', { ns: 'bs' })}
                            <span className="text-[#335CFF]">{total}</span>
                            {t('pagination.totalSuffixWithPageSize', { ns: 'bs', pageSize })}
                        </span>
                    </PaginationItem>
                )}

                <PaginationItem key="previous">
                    <PaginationPrevious
                        href="javascript:;"
                        className={page <= 1 ? 'pointer-events-none text-gray-400' : ''}
                        onClick={() => handlePageChange(page - 1)}
                    />
                </PaginationItem>

                {getPageNumbers().map((item, idx) => (
                    <PaginationItem key={`${item}-${idx}`}>
                        {item === "ellipsis" ? (
                            <span className="px-1 text-[#86909c]">...</span>
                        ) : (
                            <PaginationLink
                                href="javascript:;"
                                className={page === item ? 'font-bold' : 'text-gray-500'}
                                onClick={() => handlePageChange(item)}
                                isActive={item === page}
                            >
                                {item}
                            </PaginationLink>
                        )}
                    </PaginationItem>
                ))}

                <PaginationItem key="next">
                    <PaginationNext
                        href="javascript:;"
                        className={page >= Math.max(1, totalPages) ? 'pointer-events-none text-gray-400' : ''}
                        onClick={() => handlePageChange(page + 1)}
                    />
                </PaginationItem>

                {/* Conditionally render the "Jump to Page" input */}
                {showJumpInput && (
                    <PaginationItem key="jump">
                        <div className="flex items-center text-sm gap-1">
                            <span>{jumpToText}</span>
                            <Input
                                type="number"
                                className="w-[40px] h-6 text-center p-0"
                                boxClassName="w-auto"
                                value={jumpPage}
                                onChange={handleJumpInputChange}
                                onBlur={handleJumpInputBlur}
                                onKeyDown={(e) => e.key === 'Enter' && handleJumpPage()}
                            />
                            <span>{pageText}</span>
                        </div>
                    </PaginationItem>
                )}
            </PaginationContent>
        </Pagination>
    );
};

export default AutoPagination;