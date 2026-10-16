import { useNavigate } from 'react-router-dom';
import { Outlined } from 'bisheng-icons';
import { DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator } from '~/components/ui';
import { useLocalize } from '~/hooks';
import { useSkillCenter } from './useSkillCenter';
import { skillCenterPath } from './types';
import { SkillMenuRow } from './SkillMenuRow';

interface SkillMenuPanelProps {
  onUpload: () => void;
  onBack?: () => void;
}

export function SkillMenuPanel({ onUpload, onBack }: SkillMenuPanelProps) {
  const localize = useLocalize();
  const navigate = useNavigate();
  const { identity, platform, personal } = useSkillCenter();
  const skills = [...(platform.data ?? []), ...(personal.data ?? []).filter((skill) => skill.enabled)]
    .sort((left, right) => left.displayName.localeCompare(right.displayName));
  const loading = identity.isLoading || platform.isFetching || personal.isFetching;
  const failed = identity.isError || platform.isError || personal.isError;
  const retry = () => {
    if (identity.isError) { void identity.refetch(); return; }
    void platform.refetch();
    void personal.refetch();
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {onBack && <DropdownMenuItem onSelect={(event) => { event.preventDefault(); onBack(); }} className="shrink-0 cursor-pointer gap-2 rounded-lg px-2 py-2 text-body-sm text-text-1">
        <Outlined.ArrowLeft className="size-4" />{localize('com_skill_center_menu')}
      </DropdownMenuItem>}
      <DropdownMenuLabel className="shrink-0 px-2 pb-1 pt-2 text-caption font-normal text-text-3">{localize('com_skill_center_menu_available')}</DropdownMenuLabel>
      <div className="scrollbar-os min-h-0 flex-1 overflow-y-auto overscroll-contain pb-1">
        {loading && skills.length === 0 ? <p role="status" className="px-2 py-5 text-body-sm text-text-3">{localize('com_skill_center_loading')}</p> : skills.length ? skills.map((skill) => (
          <SkillMenuRow
            key={skill.id}
            skill={skill}
            onSelect={() => navigate(`${skillCenterPath}?skill=${encodeURIComponent(skill.id)}`)}
          />
        )) : !failed && <p className="px-2 py-5 text-body-sm text-text-3">{localize('com_skill_center_empty')}</p>}
        {failed && <div className="px-2 py-2">
          <p role="alert" className="text-caption text-text-3">{localize('com_skill_center_load_failed')}</p>
          <DropdownMenuItem disabled={loading} onSelect={(event) => { event.preventDefault(); retry(); }} className="mt-1 cursor-pointer rounded-lg text-body-sm text-text-1">{localize('com_skill_center_retry')}</DropdownMenuItem>
        </div>}
      </div>
      <DropdownMenuSeparator className="shrink-0" />
      <DropdownMenuItem onSelect={onUpload} className="h-8 shrink-0 cursor-pointer gap-2 rounded-lg px-2 text-body-sm font-normal text-text-1">
        <Outlined.Upload className="size-4 text-text-2" />{localize('com_skill_center_upload')}
      </DropdownMenuItem>
      <DropdownMenuItem onSelect={() => navigate(skillCenterPath)} className="h-8 shrink-0 cursor-pointer gap-2 rounded-lg px-2 text-body-sm font-normal text-text-1">
        <Outlined.Setting className="size-4 text-text-2" />{localize('com_skill_center_manage')}
      </DropdownMenuItem>
    </div>
  );
}
