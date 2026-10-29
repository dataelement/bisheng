import { Switch, Tag } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import type { ReactNode } from 'react';
import type { SkillRecord } from '~/components/Skills/types';
import { useLocalize } from '~/hooks';
import { DemoTag } from '~/mock/demo/DemoTag';
import { cn } from '~/utils';

export type SkillSort = 'recent' | 'name';

/** Enterprise sample rows are keyed by name (the id is derived); personal ones by id. */
const byName = (left: SkillRecord, right: SkillRecord) => left.displayName.localeCompare(right.displayName);

function updatedAt(skill: SkillRecord): number {
  const parsed = Date.parse(skill.updatedAt);
  return Number.isNaN(parsed) ? 0 : parsed;
}

/** Newest change first. A shared timestamp keeps the later row ahead. */
const byRecent = (left: SkillRecord, right: SkillRecord) => {
  const delta = updatedAt(right) - updatedAt(left);
  return delta !== 0 ? delta : right.id - left.id;
};

interface SkillRowProps {
  skill: SkillRecord;
  /** Id of the skill whose toggle is being saved — its switch shows the spinner. */
  pendingId?: number;
  onSelect: (skill: SkillRecord) => void;
  onToggle: (skill: SkillRecord, enabled: boolean) => void;
}

function SkillRow({ skill, pendingId, onSelect, onToggle }: SkillRowProps) {
  const localize = useLocalize();
  const personal = skill.source === 'personal' ? skill : null;
  const switchLabel = `${localize('com_skill_center_enabled_setting')}: ${skill.displayName}`;
  const from = localize(personal ? 'com_skill_center_from_me' : 'com_skill_center_from_platform');

  return (
    <li className="relative flex w-full items-center gap-4 border-b-[0.5px] border-border-base px-2 py-3 transition-colors hover:bg-fill-1">
      {/* The row's one action — open the details — covers the whole row; the switch sits
          above it. Update and delete live in the details. */}
      <button
        type="button"
        onClick={() => onSelect(skill)}
        aria-label={`${localize('com_skill_center_details')}: ${skill.displayName}`}
        className="absolute inset-0 rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500"
      />
      <span className="flex size-10 shrink-0 items-center justify-center rounded-lg border-[0.5px] border-border-base bg-white text-text-2">
        <Outlined.Skill className="size-[18px]" />
      </span>
      <div className="pointer-events-none min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-1.5">
          <h3 className={cn('min-w-0 truncate text-body font-medium', personal?.enabled === false ? 'text-text-3' : 'text-text-1')}>
            {skill.displayName}
          </h3>
          <DemoTag id={String(skill.id)} className="shrink-0" />
          {personal?.enabled === false && (
            <Tag className="shrink-0">{localize('com_skill_center_disabled_tag')}</Tag>
          )}
        </div>
        <p className="mt-0.5 truncate text-caption text-text-3">
          {from}
          <span aria-hidden className="mx-1.5">·</span>
          {skill.description}
        </p>
      </div>
      {(
        <Switch
          size="small"
          className="relative z-[1] shrink-0"
          checked={skill.enabled}
          loading={pendingId === skill.id}
          disabled={pendingId !== undefined && pendingId !== skill.id}
          aria-label={switchLabel}
          onCheckedChange={(enabled) => onToggle(skill, enabled)}
        />
      )}
    </li>
  );
}

interface SkillGroupProps {
  title: string;
  count: number;
  children: ReactNode;
}

function SkillGroup({ title, count, children }: SkillGroupProps) {
  return (
    <section className="flex w-full flex-col">
      <h2 className="flex items-center gap-1.5 px-2 pb-2 text-body-sm font-medium text-text-1">
        {title}
        <span className="font-normal text-text-3">· {count}</span>
      </h2>
      {children}
    </section>
  );
}

interface SkillListProps extends Omit<SkillRowProps, 'skill'> {
  /** Already filtered by the search keyword. */
  skills: SkillRecord[];
  sort: SkillSort;
  createdCount?: number;
  providedCount?: number;
  /** Shown under 我创建的 while it is empty (and nothing is being searched for). */
  createdEmptyHint?: ReactNode;
}

/**
 * 我的技能 as one list in two groups — what the user made, then what the enterprise gave
 * this account — so "every skill I can use" reads top to bottom in one place. Rows are
 * dense on purpose: name, where it came from, and one line of description. Only a skill
 * the user created has an on / off switch. Clicking a row opens its details.
 */
export function SkillList({ skills, sort, createdCount, providedCount, createdEmptyHint, ...rowProps }: SkillListProps) {
  const localize = useLocalize();
  const compare = sort === 'name' ? byName : byRecent;
  const created = skills.filter((skill) => skill.source === 'personal').sort(compare);
  const provided = skills.filter((skill) => skill.source === 'platform').sort(compare);

  return (
    <div className="flex w-full flex-col gap-6">
      {(created.length > 0 || createdEmptyHint) && (
        <SkillGroup title={localize('com_skill_center_group_created')} count={createdCount ?? created.length}>
          {created.length > 0 ? (
            <ul className="flex w-full flex-col">
              {created.map((skill) => <SkillRow key={skill.id} skill={skill} {...rowProps} />)}
            </ul>
          ) : (
            createdEmptyHint
          )}
        </SkillGroup>
      )}
      {provided.length > 0 && (
        <SkillGroup title={localize('com_skill_center_group_platform')} count={providedCount ?? provided.length}>
          <ul className="flex w-full flex-col">
            {provided.map((skill) => <SkillRow key={skill.id} skill={skill} {...rowProps} />)}
          </ul>
        </SkillGroup>
      )}
    </div>
  );
}

/** First-load placeholder, same footprint as the real rows. */
export function SkillListSkeleton() {
  const localize = useLocalize();
  return (
    <div role="status" aria-label={localize('com_skill_center_loading')} className="flex w-full flex-col">
      {Array.from({ length: 6 }, (_, item) => (
        <div key={item} className="flex items-center gap-3 border-b-[0.5px] border-border-base px-2 py-3 motion-safe:animate-pulse">
          <div className="size-10 shrink-0 rounded-lg bg-fill-2" />
          <div className="min-w-0 flex-1">
            <div className="h-4 w-1/4 rounded bg-fill-2" />
            <div className="mt-2 h-3 w-2/3 rounded bg-fill-1" />
          </div>
        </div>
      ))}
    </div>
  );
}
