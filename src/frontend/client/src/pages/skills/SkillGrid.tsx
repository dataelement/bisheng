import { Outlined } from 'bisheng-icons';
import { useLocalize } from '~/hooks';
import type { CenterSkill } from '~/components/Skills/types';
import { DemoTag } from '~/mock/demo/DemoTag';

/** Same card grid as the other module homes: fills the 1000px column, 3-up at full width. */
const GRID = 'grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-3';

interface SkillCardProps {
  skill: CenterSkill;
  onSelect: (skill: CenterSkill) => void;
}

function SkillCard({ skill, onSelect }: SkillCardProps) {
  const localize = useLocalize();
  return (
    <button
      type="button"
      onClick={() => onSelect(skill)}
      className="group flex min-h-32 min-w-0 flex-col rounded-lg border border-border-base p-4 text-left transition-colors hover:border-blue-300 hover:bg-fill-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
    >
      <div className="flex w-full items-start gap-3">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-fill-1 text-text-2 group-hover:bg-fill-2">
          <Outlined.Newspaper className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-1">
            <h3 className="min-w-0 truncate text-body font-medium text-text-1" title={skill.displayName}>{skill.displayName}</h3>
            {/* Enterprise sample rows are keyed by name (the id is derived); personal ones by id. */}
            <DemoTag id={skill.source === 'platform' ? skill.name : skill.id} className="shrink-0" />
          </div>
          <p className="mt-0.5 truncate text-caption text-text-3">{skill.name}</p>
        </div>
        {/* Hover / focus affordance; touch devices have no hover, so it stays visible there. */}
        <span className="pointer-events-none shrink-0 whitespace-nowrap text-caption text-text-2 opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100 coarse-pointer:opacity-100">
          {localize('com_skill_center_details')}<span aria-hidden className="ml-1">→</span>
        </span>
      </div>
      <p className="mt-2 line-clamp-2 break-words text-body-sm text-text-3">{skill.description}</p>
    </button>
  );
}

interface SkillGridProps {
  skills: CenterSkill[];
  onSelect: (skill: CenterSkill) => void;
}

export function SkillGrid({ skills, onSelect }: SkillGridProps) {
  return (
    <div className={GRID}>
      {skills.map((skill) => <SkillCard key={skill.id} skill={skill} onSelect={onSelect} />)}
    </div>
  );
}

/** First-load placeholder, same footprint as the real cards. */
export function SkillGridSkeleton() {
  const localize = useLocalize();
  return (
    <div role="status" aria-label={localize('com_skill_center_loading')} className={GRID}>
      {Array.from({ length: 6 }, (_, item) => (
        <div key={item} className="h-32 rounded-lg border border-border-base p-4 motion-safe:animate-pulse">
          <div className="h-5 w-1/2 rounded bg-fill-2" />
          <div className="mt-4 h-3 w-full rounded bg-fill-1" />
          <div className="mt-2 h-3 w-3/4 rounded bg-fill-1" />
        </div>
      ))}
    </div>
  );
}
