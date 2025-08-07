// components/SopTable.tsx
import { useState } from 'react';
import { ChevronUp, ChevronDown, Star, Check } from 'lucide-react';
import AutoPagination from '../bs-ui/pagination/autoPagination';
import { LoadIcon } from '../bs-icons';
import { Button } from '../bs-ui/button';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '../bs-ui/tooltip';

const SopTable = ({
    datalist,
    selectedItems,
    handleSelectItem,
    handleSelectAll,
    handleSort,
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
    handleKeyDown
}) => {
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
            <span className="text-sm text-gray-400">暂无评分</span>
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
    datalist.every(item => selectedItems.includes(item.id)) }
                            >
                                {datalist.length > 0 && 
    datalist.every(item => selectedItems.includes(item.id)) && (
                                    <Check className="w-3 h-3 text-white" />
                                )}
                            </button>
                        </th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">名称</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">描述</th>
                        {/* <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            <div className="flex items-center h-full">
                                <span className="align-middle">星级评分</span>
                                {loading && <LoadIcon className="animate-spin w-4 h-4 ml-1" />}
                                <div className="flex flex-col ml-1">
                                    <button
                                        onClick={() => handleSort('rating', 'asc')}
                                        disabled={loading}
                                    >
                                        <ChevronUp className={`w-3 h-3 ${loading ? 'text-gray-300' : 'text-gray-400 hover:text-gray-600'}`} />
                                    </button>
                                    <button
                                        onClick={() => handleSort('rating', 'desc')}
                                        disabled={loading}
                                    >
                                        <ChevronDown className={`w-3 h-3 ${loading ? 'text-gray-300' : 'text-gray-400 hover:text-gray-600'}`} />
                                    </button>
                                </div>
                            </div>
                        </th> */}
                        <th className="px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">操作</th>
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
                                            <TooltipContent className='max-w-[700px] break-words whitespace-normal'>
                                                <p>{item.name}</p>
                                            </TooltipContent>
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
                                {/* <td className="px-6 py-4 whitespace-nowrap">
                                    {ratingDisplay(item.rating || 0)}
                                </td> */}
                                <td className="px-6 py-4 whitespace-nowrap text-center text-sm font-medium">
                                    <Button
                                        variant="ghost"
                                        className="text-blue-600 hover:text-blue-900 mr-3"
                                        onClick={() => handleEdit(item.id)}
                                    >
                                        编辑
                                    </Button>
                                    <Button
                                        variant="ghost"
                                        onClick={() => handleDelete(item.id)}
                                        className="text-red-600 hover:text-red-900"
                                    >
                                        删除
                                    </Button>
                                </td>
                            </tr>
                        ))
                    ) : (
                        <tr>
                            <td colSpan="5" className="px-6 py-4 text-center text-sm text-gray-500">
                                未找到相关SOP
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
                        <span className="text-sm text-gray-700 mr-2 whitespace-nowrap">跳至</span>
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
                            页
                        </span>
                        {loading && <LoadIcon className="animate-spin w-4 h-4 ml-2" />}
                    </div>
                </div>
            )}
        </div>
    );
};

export default SopTable;