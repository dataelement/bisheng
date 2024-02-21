import { Pagination, PaginationContent, PaginationEllipsis, PaginationItem, PaginationLink, PaginationNext, PaginationPrevious } from '../ui/pagination';

const PaginationComponent = ({ page, pageSize, total, maxVisiblePages = 5, onChange }) => {
    const totalPages = Math.ceil(total / pageSize);

    const handlePageChange = (newPage) => {
        if (newPage >= 1 && newPage <= totalPages && newPage !== page) {
            onChange(newPage);
        }
    };

    const renderPaginationItems = () => {
        const items = [];

        // Previous Button
        items.push(
            <PaginationItem key="previous">
                <PaginationPrevious href="#" onClick={() => handlePageChange(page - 1)} />
            </PaginationItem>
        );

        // Page Buttons
        if (totalPages <= maxVisiblePages) {
            // If total pages are less than or equal to maxVisiblePages, show all pages
            for (let i = 1; i <= totalPages; i++) {
                items.push(
                    <PaginationItem key={i}>
                        <PaginationLink href="#" onClick={() => handlePageChange(i)} isActive={i === page}>
                            {i}
                        </PaginationLink>
                    </PaginationItem>
                );
            }
        } else {
            // If total pages are more than maxVisiblePages, show at most maxVisiblePages pages
            const startPage = Math.max(1, page - Math.floor(maxVisiblePages / 2));
            const endPage = Math.min(totalPages, startPage + maxVisiblePages - 1);

            if (startPage > 1) {
                // Display ellipsis if there are pages before the startPage
                items.push(
                    <PaginationItem key="startEllipsis">
                        <PaginationEllipsis />
                    </PaginationItem>
                );
            }

            for (let i = startPage; i <= endPage; i++) {
                items.push(
                    <PaginationItem key={i}>
                        <PaginationLink href="#" onClick={() => handlePageChange(i)} isActive={i === page}>
                            {i}
                        </PaginationLink>
                    </PaginationItem>
                );
            }

            if (endPage < totalPages) {
                // Display ellipsis if there are pages after the endPage
                items.push(
                    <PaginationItem key="endEllipsis">
                        <PaginationEllipsis />
                    </PaginationItem>
                );
            }
        }

        // Next Button
        items.push(
            <PaginationItem key="next">
                <PaginationNext href="#" onClick={() => handlePageChange(page + 1)} />
            </PaginationItem>
        );

        return items;
    };

    return (
        <Pagination>
            <PaginationContent>{renderPaginationItems()}</PaginationContent>
        </Pagination>
    );
};

export default PaginationComponent;
