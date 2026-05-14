import type { TFile } from '~/types/chat';
import { useGetFiles } from '~/hooks/queries/data-provider';
import { columns } from './PanelColumns';
import DataTable from './PanelTable';

export default function FilesPanel() {
  const { data: files = [] } = useGetFiles<TFile[]>();

  return (
    <div className="h-auto max-w-full overflow-x-hidden">
      <DataTable columns={columns} data={files} />
    </div>
  );
}
