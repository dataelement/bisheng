import type { PaginationLocale } from '@bisheng/ui';
import { useTranslation } from 'react-i18next';

/** Localized copy for the shared Pagination, independent of the page's namespace. */
export function usePaginationLocale(): PaginationLocale {
    const { t } = useTranslation('bs');
    return {
        total: (total) => t('pagination.total', { total }),
        pageSize: (size) => t('pagination.pageSize', { size }),
        jumpPrefix: t('pagination.jumpPrefix'),
        jumpSuffix: t('pagination.jumpSuffix'),
        jumpError: (totalPages) => t('pagination.jumpError', { totalPages }),
        prev: t('pagination.prev'),
        next: t('pagination.next'),
        nav: t('pagination.nav'),
        pageSizeAria: t('pagination.pageSizeAria'),
        jumpAria: t('pagination.jumpAria'),
    };
}
