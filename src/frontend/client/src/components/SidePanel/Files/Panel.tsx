import type { TFile } from '~/data-provider/data-provider/src';
import { useGetFiles } from '~/data-provider';
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
