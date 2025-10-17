import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/bs-ui/tooltip';
import {
    Download
} from 'lucide-react';
import { useState } from 'react';
import FileIcon from './FileIcon';


export default function DownloadList({ file, onDownloadFile, onExportOther }) {
    const [tooltipOpen, setTooltipOpen] = useState(false);

    return <Tooltip
        open={tooltipOpen}
        delayDuration={1}
        onOpenChange={setTooltipOpen}
    >
        <TooltipTrigger asChild>
            <span onClick={(e) => e.stopPropagation()}>
                <Download size={16} onClick={() => { setTooltipOpen(true) }} />
            </span>
        </TooltipTrigger>
        <TooltipContent side='bottom' align='center' className='bg-white text-gray-800 border border-gray-200'>
            <div className='flex flex-col gap-2'>
                <div className='flex gap-2 items-center cursor-pointer hover:bg-gray-100 rounded-md p-1' onClick={(e) => { e.stopPropagation(); onDownloadFile(file); setTooltipOpen(false); }}>
                    <FileIcon type={'md'} className='size-5' />
                    <div className='w-full flex gap-2 items-center'>Markdown</div>
                </div>
                <div className='flex gap-2 items-center rounded-md p-1 cursor-pointer hover:bg-gray-100' onClick={(e) => { e.stopPropagation(); onExportOther(e, 'pdf', file); setTooltipOpen(false); }}>
                    <FileIcon type={'pdf'} className='size-5' />
                    <div className='w-full flex gap-2 items-center'>PDF</div>
                </div>
                <div className='flex gap-2 items-center rounded-md p-1 cursor-pointer hover:bg-gray-100' onClick={(e) => { e.stopPropagation(); onExportOther(e, 'docx', file); setTooltipOpen(false); }}>
                    <FileIcon type={'docx'} className='size-5' />
                    <div className='w-full flex gap-2 items-center'>Docx</div>
                </div>
            </div>
        </TooltipContent>
    </Tooltip>
};
