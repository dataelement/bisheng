import { Download } from 'lucide-react';
import FileIcon from '~/components/ui/icon/File';
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '../../ui';

export default function DownloadResultFileBtn({ file, onDownloadFile }) {

    const isMd = /md$/i.test(file.file_name)

    const handleClick = (e, url) => {
        e.stopPropagation();
        onDownloadFile({
            file_name: file.file_name,
            file_url: url
        })
    }

    const handleDownLoad = (e, type) => {
        e.stopPropagation();
        // loading
    }

    if (!isMd) return <Button variant="ghost" className=' w-6 h-6 p-0'>
        <Download size={16} onClick={(e) => {
            e.stopPropagation();
            onDownloadFile({
                file_name: file.file_name,
                file_url: file.file_url
            })
        }} />
    </Button>

    return <DropdownMenu>
        {/* tooltip */}
        <DropdownMenuTrigger asChild>
            <span>
                <Download size={16} className='text-gray-500' />
            </span>
        </DropdownMenuTrigger>
        <DropdownMenuContent className='w-60 rounded-2xl'>
            <DropdownMenuItem className='select-item text-sm font-normal' onClick={(e) => handleClick(e, file.file_url)}>
                <FileIcon type={'md'} className='size-5' />
                <div className='w-full flex gap-2 items-center' >
                    Markdown
                </div>
            </DropdownMenuItem>
            <DropdownMenuItem className='select-item text-sm font-normal' onClick={(e) => handleDownLoad(e, 'pdf')}>
                <FileIcon type={'pdf'} className='size-5' />
                <div className='w-full flex gap-2 items-center' >
                    PDF
                </div>
            </DropdownMenuItem>
            <DropdownMenuItem className='select-item text-sm font-normal' onClick={(e) => handleDownLoad(e, 'docx')}>
                <FileIcon type={'docx'} className='size-5' />
                <div className='w-full flex gap-2 items-center' >
                    Docx
                </div>
            </DropdownMenuItem>
        </DropdownMenuContent>
    </DropdownMenu>
};
