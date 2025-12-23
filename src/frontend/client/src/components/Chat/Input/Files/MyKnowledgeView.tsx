import axios from 'axios';
import { useEffect, useState } from 'react';
import { NotificationSeverity } from '~/common';
import { OGDialog, OGDialogContent, OGDialogHeader, OGDialogTitle } from '~/components';
import { useGetDownloadUrl, useGetKnowledgeFiles, useModelBuilding } from '~/data-provider';
import type { TFile } from '~/data-provider/data-provider/src';
import { dataService } from '~/data-provider/data-provider/src';
import { useLocalize, useToast } from '~/hooks';
import { DataTableKnowledge, getKnowledgeColumns } from './Table';

export default function MyKnowledgeView({ open, onOpenChange }) {
  const localize = useLocalize();
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)

  const { data = { list: [], total: 1 }, refetch } = useGetKnowledgeFiles<TFile[]>([page, keyword], {

    select: (files) => {
      // setTotal(files.data.total)
      return {
        list: files.data.list || [],
        total: files.data.total || 1,
      };
      // files.map((file) => {
      //   file.context = file.context ?? FileContext.unknown;
      //   file.filterSource = file.source === FileSources.firebase ? FileSources.local : file.source;
      //   return file;
      // })
    },
    refetchInterval: 10000, // 10s一刷新
  });

  const handleDownload = async (id: string, filename: string) => {
    if (building) return backToast()

    const res = await useGetDownloadUrl(id)

    return axios.get(__APP_ENV__.BASE_URL + res.data.original_url, { responseType: "blob" }).then((res: any) => {
      const blob = new Blob([res.data]);
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = filename;
      link.click();
      URL.revokeObjectURL(link.href);
    }).catch(console.error);

    // try {
    //   const link = document.createElement('a');
    //   link.href = res.data;
    //   link.download = filename;
    //   document.body.appendChild(link);
    //   link.click();
    //   document.body.removeChild(link);
    // } catch (error) {
    //   console.error('Download failed:', error);
    // }
  };

  const handleDelete = async (id) => {
    if (building) return backToast()

    try {
      const res = await dataService.deleteKnowledge(id);
      console.info(res);
      refetch()
    } catch (error) {
      console.error('delete failed:', error);
    }
  };

  const { showToast } = useToast()
  const backToast = () => {
    showToast({
      message: localize('com_tools_knowledge_rebuilding'),
      severity: NotificationSeverity.WARNING,
    })
  }

  const [building] = useModelBuilding()

  return (
    <OGDialog open={open} onOpenChange={onOpenChange}>
      <OGDialogContent
        // title={localize('com_nav_my_knowledge_files')}
        className="w-11/12 bg-background text-text-primary shadow-2xl"
      >
        <OGDialogHeader>
          <OGDialogTitle>{localize('com_nav_my_knowledge_files')}</OGDialogTitle>
        </OGDialogHeader>
        <DataTableKnowledge columns={getKnowledgeColumns(handleDelete, handleDownload)}
          building={building}
          data={data}
          page={page}
          onPage={setPage}
          onSearch={setKeyword}
          onUpload={refetch}
        />
      </OGDialogContent>
    </OGDialog>
  );
}
