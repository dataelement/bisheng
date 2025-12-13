// components/SopTable.tsx
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@radix-ui/react-dropdown-menu';
import { Check, Filter, Star } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { LoadIcon } from '../bs-icons';
import { Button } from '../bs-ui/button';
import AutoPagination from '../bs-ui/pagination/autoPagination';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '../bs-ui/tooltip';

const SopTable = ({
    datalist,
    selectedItems,
    handleSelectItem,
    handleSelectAll,
    handleEdit,
    handleDelete,
    page,
    pageSize,
    total,
    loading,
    pageInputValue,
    handlePageChange,
    handlePageInputChange,
    handlePageInputConfirm,
    handleKeyDown,
    onShowcaseFilterChange
}) => {
    // Whether the featured filter is selected: state management (similar to Files.tsx)
    const [featuredSelectedFilters, setFeaturedSelectedFilters] = useState<number[]>([]);
    const [featuredTempFilters, setFeaturedTempFilters] = useState<number[]>([]);
    const [isFeaturedFilterOpen, setIsFeaturedFilterOpen] = useState(false);
    const { t } = useTranslation()

    const applyFeaturedFilters = () => {
        setFeaturedSelectedFilters([...featuredTempFilters]);
        setIsFeaturedFilterOpen(false);
        // Pass to parent component: Only effective when selecting single 1 or 0; multiple selections or empty means no filter
        if (Array.isArray(featuredTempFilters)) {
            if (featuredTempFilters.length === 1) {
                const value = featuredTempFilters[0];
                onShowcaseFilterChange?.(value === 1 ? 1 : 0);
            } else {
                onShowcaseFilterChange?.(undefined);
            }
        } else {
            onShowcaseFilterChange?.(undefined);
        }
    };

    const resetFeaturedFilters = () => {
        const empty: number[] = [];
        setFeaturedTempFilters(empty);
        setFeaturedSelectedFilters(empty);
        onShowcaseFilterChange?.(undefined);
        setIsFeaturedFilterOpen(false);
    };

    const handleFeaturedOpenChange = (open: boolean) => {
        if (open) {
            setFeaturedTempFilters([...featuredSelectedFilters]);
        }
        setIsFeaturedFilterOpen(open);
    };

    const ratingDisplay = (rating) => {
        return rating > 0 ? (
            <div className="flex items-center">
                {[...Array(5)].map((_, i) => (
                    <Star
                        key={i}
                        className={`w-4 h-4 ${i < rating ? 'text-yellow-400' : 'text-gray-300'}`}
                    />
                ))}
            </div>
        ) : (
            <span className="text-sm text-gray-400">{t('importLinsight.noRatings')}</span>
        );
    };

    return (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                    <tr>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            <button
                                type="button"
                                className={`h-4 w-4 rounded border flex items-center justify-center transition-colors ${datalist.length > 0 &&
                                    datalist.every(item => selectedItems.includes(item.id))
                                    ? 'bg-blue-600 border-blue-600'
                                    : 'bg-white border-gray-300'
                                    }`}
                                style={{ color: 'white' }}
                                onClick={(e) => {
                                    handleSelectAll();
                                }}
                                aria-pressed={datalist.length > 0 &&
                                    datalist.every(item => selectedItems.includes(item.id))}
                            >
                                {datalist.length > 0 &&
                                    datalist.every(item => selectedItems.includes(item.id)) && (
                                        <Check className="w-3 h-3 text-white" />
                                    )}
                            </button>
                        </th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('importLinsight.name')}</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('importLinsight.creator')}</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('importLinsight.description')}</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            <div className="flex items-center gap-2">
                                <span>{t('importLinsight.featured')}</span>
                                <div className="relative">
                                    <DropdownMenu open={isFeaturedFilterOpen} onOpenChange={handleFeaturedOpenChange}>
                                        <DropdownMenuTrigger asChild>
                                            <Button
                                                variant="ghost"
                                                className={`flex items-center gap-1 ${featuredSelectedFilters.length > 0 ? 'text-blue-500' : ''}`}
                                            >
                                                <Filter size={16} />
                                            </Button>
                                        </DropdownMenuTrigger>
                                        <DropdownMenuContent
                                            className="h-full p-0 shadow-lg rounded-md border"
                                            style={{ backgroundColor: 'white', opacity: 1 }}
                                            align="end"
                                        >
                                            <div className="px-2">
                                                {[
                                                    { value: 1, label: t('importLinsight.featured') },
                                                    { value: 0, label: t('importLinsight.notFeatured') }
                                                ].map(({ value, label }) => (
                                                    <div
                                                        key={value}
                                                        className="flex items-center gap-3 px-2 py-3 hover:bg-gray-100 rounded cursor-pointer"
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            setFeaturedTempFilters(prev =>
                                                                prev.includes(value)
                                                                    ? prev.filter(v => v !== value)
                                                                    : [...prev, value]
                                                            );
                                                        }}
                                                    >
                                                        <input
                                                            type="checkbox"
                                                            checked={featuredTempFilters.includes(value)}
                                                            onChange={() => { }}
                                                            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                                                        />
                                                        <div className="flex items-center gap-2">
                                                            <span>{label}</span>
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                            <div className="border-t border-gray-200"></div>
                                            <div className="flex justify-end gap-2 px-3 py-2">
                                                <Button
                                                    variant="ghost"
                                                    size="sm"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        resetFeaturedFilters();
                                                    }}
                                                    disabled={featuredTempFilters.length === 0}
                                                >
                                                    {t('importLinsight.reset')}
                                                </Button>
                                                <Button
                                                    size="sm"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        applyFeaturedFilters();
                                                    }}
                                                >
                                                    {t('importLinsight.apply')}
                                                </Button>
                                            </div>
                                        </DropdownMenuContent>
                                    </DropdownMenu>
                                </div>
                            </div>
                        </th>
                        <th className="px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">{t('importLinsight.actions')}</th>
                    </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                    {datalist.length > 0 ? (
                        datalist.map((item) => (
                            <tr key={item.id}>
                                <td className="px-6 py-4 whitespace-nowrap">
                                    <button
                                        type="button"
                                        className="relative h-4 w-4 rounded border flex items-center justify-center"
                                        style={{
                                            backgroundColor: selectedItems.includes(item.id) ? '#2563eb' : 'white',
                                            borderColor: selectedItems.includes(item.id) ? '#2563eb' : '#d1d5db',
                                            color: "white"
                                        }}
                                        onClick={() => handleSelectItem(item.id)}
                                    >
                                        {selectedItems.includes(item.id) && (
                                            <Check className="w-3 h-3 text-white" />
                                        )}
                                    </button>
                                </td>
                                <td className="px-6 py-4 whitespace-nowrap max-w-[200px]">
                                    <TooltipProvider>
                                        <Tooltip>
                                            <TooltipTrigger asChild>
                                                <div className="text-sm font-medium text-gray-900 truncate">
                                                    {item.name}
                                                </div>
                                            </TooltipTrigger>
                                            <TooltipContent align="start" className='max-w-[700px] break-words whitespace-normal text-left'>
                                                <p>{item.name}</p>
                                            </TooltipContent>
                                        </Tooltip>
                                    </TooltipProvider>
                                </td>
                                <td className="px-6 py-4 whitespace-nowrap max-w-[200px]">
                                    <TooltipProvider>
                                        <Tooltip>
                                            <TooltipTrigger asChild>
                                                <div className="text-sm font-medium text-gray-900 truncate">
                                                    {item.user_name}
                                                </div>
                                            </TooltipTrigger>
                                        </Tooltip>
                                    </TooltipProvider>
                                </td>
                                <td className="px-6 py-4 max-w-[300px]">
                                    <TooltipProvider>
                                        <Tooltip>
                                            <TooltipTrigger asChild>
                                                <div className="text-sm text-gray-500 truncate">
                                                    {item.description}
                                                </div>
                                            </TooltipTrigger>
                                            <TooltipContent className="max-w-[900px] break-words whitespace-normal">
                                                <p className="text-sm">{item.description}</p>
                                            </TooltipContent>
                                        </Tooltip>
                                    </TooltipProvider>
                                </td>
                                <td className="px-6 py-4 whitespace-nowrap max-w-[200px]">
                                    <TooltipProvider>
                                        <Tooltip>
                                            <TooltipTrigger asChild>
                                                <div className="text-sm font-medium text-gray-500 truncate">
                                                    {item.showcase ? t('importLinsight.featured') : t('importLinsight.notFeatured')}
                                                </div>
                                            </TooltipTrigger>
                                        </Tooltip>
                                    </TooltipProvider>
                                </td>
                                {/* <td className="px-6 py-4 whitespace-nowrap">
                                    {ratingDisplay(item.rating || 0)}
                                </td> */}
                                <td className="px-6 py-4 whitespace-nowrap text-center text-sm font-medium">
                                    <Button
                                        variant="ghost"
                                        className="text-blue-600 hover:text-blue-900 mr-3"
                                        onClick={() => handleEdit(item.id)}
                                    >
                                        {t('importLinsight.edit')}
                                    </Button>
                                    <Button
                                        variant="ghost"
                                        onClick={() => handleDelete(item.id)}
                                        className="text-red-600 hover:text-red-900"
                                    >
                                        {t('importLinsight.delete')}
                                    </Button>
                                </td>
                            </tr>
                        ))
                    ) : (
                        <tr>
                            <td colSpan={5} className="px-6 py-4 text-center text-sm text-gray-500">
                                {t('importLinsight.noSOPFound')}
                            </td>
                        </tr>
                    )}
                </tbody>
            </table>

            {datalist.length > 0 && (
                <div className="px-6 py-3 flex items-center justify-between border-t border-gray-200">
                    <div className="flex items-center">
                    </div>
                    <div className="flex items-center ml-4">
                        <AutoPagination
                            page={page}
                            pageSize={pageSize}
                            total={total}
                            onChange={(newPage) => handlePageChange(newPage)}
                        />
                        <span className="text-sm text-gray-700 mr-2 whitespace-nowrap">{t('importLinsight.goTo')}</span>
                        <input
                            type="number"
                            min="1"
                            max={Math.max(1, Math.ceil(total / pageSize))}
                            value={pageInputValue}
                            onChange={handlePageInputChange}
                            onBlur={handlePageInputConfirm}
                            onKeyDown={handleKeyDown}
                            className="w-16 px-2 py-1 border rounded text-sm text-center"
                            disabled={loading}
                        />
                        <span className="text-sm text-gray-700 ml-2 whitespace-nowrap">
                            {t('importLinsight.pages')}
                        </span>
                        {loading && <LoadIcon className="animate-spin w-4 h-4 ml-2" />}
                    </div>
                </div>
            )}
        </div>
    );
};

export default SopTable;
