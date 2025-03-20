import { useState } from 'react';
import { ChevronsLeft, ChevronsRight } from 'lucide-react';
import { Pagination, PaginationContent, PaginationItem, PaginationLink, PaginationNext, PaginationPrevious } from './index';
import { Input } from '../input';

interface IProps {
    /** 当前页码 */
    page: number,
    /** limit */
    pageSize: number,
    /** item total */
    total: number,
    /** 最多同时显示 item 数 */
    maxVisiblePages?: number,
    /** Function to handle page change */
    onChange?: (p: number) => void,
    className?: string,
    /** 是否开启跳转页功能 */
    showJumpInput?: boolean
}

const AutoPagination = ({ page, pageSize, total, maxVisiblePages = 5, className, onChange, showJumpInput = false }: IProps) => {
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

    const renderPaginationItems = () => {
        const items = [];
        const startPage = Math.max(1, page - Math.floor(maxVisiblePages / 2));
        const endPage = Math.min(totalPages || 1, startPage + maxVisiblePages - 1);

        if (page !== 1) {
            items.push(
                <PaginationItem key="start">
                    <PaginationLink href="javascript:;" onClick={() => handlePageChange(1)}>
                        <ChevronsLeft />
                    </PaginationLink>
                </PaginationItem>
            );
        }

        items.push(
            <PaginationItem key="previous">
                <PaginationPrevious href="javascript:;"
                    className={page === startPage && 'text-gray-400'}
                    onClick={() => handlePageChange(page - 1)} />
            </PaginationItem>
        );

        for (let i = startPage; i <= endPage; i++) {
            items.push(
                <PaginationItem key={i}>
                    <PaginationLink href="javascript:;"
                        className={page === i ? 'font-bold' : 'text-gray-500'}
                        onClick={() => handlePageChange(i)} isActive={i === page}>
                        {i}
                    </PaginationLink>
                </PaginationItem>
            );
        }

        items.push(
            <PaginationItem key="next">
                <PaginationNext href="javascript:;"
                    className={page === endPage && 'text-gray-400'}
                    onClick={() => handlePageChange(page + 1)} />
            </PaginationItem>
        );

        if (page !== totalPages) {
            items.push(
                <PaginationItem key="end">
                    <PaginationLink href="javascript:;" onClick={() => handlePageChange(totalPages)} >
                        <ChevronsRight />
                    </PaginationLink>
                </PaginationItem>
            );
        }

        return items;
    };

    return (
        <Pagination className={className}>
            <PaginationContent>
                {renderPaginationItems()}

                {/* Conditionally render the "Jump to Page" input */}
                {showJumpInput && (
                    <PaginationItem key="jump">
                        <div className="flex items-center text-sm gap-1">
                            <span>跳至</span>
                            <Input
                                type="number"
                                className="w-[40px] h-6 text-center p-0"
                                boxClassName="w-auto"
                                value={jumpPage}
                                onChange={handleJumpInputChange}
                                onBlur={handleJumpInputBlur}
                                onKeyDown={(e) => e.key === 'Enter' && handleJumpPage()}
                            />
                            <span>页</span>
                        </div>
                    </PaginationItem>
                )}
            </PaginationContent>
        </Pagination>
    );
};

export default AutoPagination;