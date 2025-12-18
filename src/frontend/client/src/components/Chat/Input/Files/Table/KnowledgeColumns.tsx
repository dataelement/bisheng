import { ArrowUpDown, Database, Download, TrashIcon } from 'lucide-react';
import { FileSources, FileContext, dataService } from '~/data-provider/data-provider/src';
import type { ColumnDef } from '@tanstack/react-table';
import type { TFile } from '~/data-provider/data-provider/src';
import { Button, Checkbox, OpenAIMinimalIcon, AzureMinimalIcon } from '~/components';
import ImagePreview from '~/components/Chat/Input/Files/ImagePreview';
import FilePreview from '~/components/Chat/Input/Files/FilePreview';
import { SortFilterHeader } from './SortFilterHeader';
import { TranslationKeys, useLocalize, useMediaQuery } from '~/hooks';
import { formatDate, getFileType } from '~/utils';

const contextMap: Record<any, TranslationKeys> = {
  [FileContext.avatar]: 'com_ui_avatar',
  [FileContext.unknown]: 'com_ui_unknown',
  [FileContext.assistants]: 'com_ui_assistants',
  [FileContext.image_generation]: 'com_ui_image_gen',
  [FileContext.assistants_output]: 'com_ui_assistants_output',
  [FileContext.message_attachment]: 'com_ui_attachment',
};

export const getKnowledgeColumns = (
  handleDelete: (row: any) => void,
  handleDownload: (row: any) => void
): ColumnDef<TFile>[] => {
  const localize = useLocalize();

  return [
    {
      meta: {
        size: '150px',
      },
      accessorKey: 'file_name',
      header: ({ column }) => {
        return localize('com_ui_name');
      },
    },
    {
      accessorKey: 'update_time',
      header: ({ column }) => {
        return localize('com_knowledge_upload_time');
      },
      cell: ({ row }) => {
        return row.original.update_time.replace('T', ' ');
      },
    },
    {
      accessorKey: 'status',
      header: ({ column }) => {
        return localize('com_knowledge_status');
      },
      cell: ({ row }) => {
        const statusTexts = [
          '', 
          localize('com_knowledge_processing'), 
          localize('com_knowledge_success'), 
          localize('com_knowledge_failed'), 
          localize('com_knowledge_model_switching')
        ];
        return statusTexts[row.original.status];
      },
    },
    {
      accessorKey: 'operate',
      header: ({ column }) => {
        return localize('com_knowledge_operation');
      },
      cell: ({ row }) => {
        return (
          <div className="flex items-center gap-3">
            <div
              className="cursor-pointer rounded-md px-2 py-1 hover:bg-gray-100"
              onClick={() => handleDownload(row.original.id, row.original.file_name)}
            >
              <Download className="h-5 w-5" />
            </div>
            <div
              className="cursor-pointer rounded-md text-red-700 px-2 py-1 hover:bg-gray-100"
              onClick={() => handleDelete(row.original.id)}
            >
              <TrashIcon className="h-5 w-5" />
            </div>
          </div>
        );
      },
    },
  ];
};