import { Button } from "@/components/bs-ui/button"
import { Input } from "@/components/bs-ui/input"
import type {
  DeveloperTokenFileSyncTargetDisplay,
  DeveloperTokenFileSyncTargetFolderOption,
  DeveloperTokenFileSyncTargetSpaceGroup,
} from "@/controllers/API/developerToken"
import { useState } from "react"
import { useTranslation } from "react-i18next"
import useDeveloperTokenFileSyncTargetTree from "./useDeveloperTokenFileSyncTargetTree"

interface TargetValue {
  knowledge_id: number | null
  folder_id: number | null
}

interface DeveloperTokenFileSyncTargetTreeProps {
  tenantId: number
  userId: number
  groups: DeveloperTokenFileSyncTargetSpaceGroup[]
  value: TargetValue
  display: DeveloperTokenFileSyncTargetDisplay | null
  loading: boolean
  error: string | null
  onChange: (value: TargetValue) => void
  onSearchSpaces: (keyword: string) => void
}

export default function DeveloperTokenFileSyncTargetTree({
  tenantId,
  userId,
  groups,
  value,
  display,
  loading,
  error,
  onChange,
  onSearchSpaces,
}: DeveloperTokenFileSyncTargetTreeProps) {
  const { t } = useTranslation()
  const [keyword, setKeyword] = useState("")
  const tree = useDeveloperTokenFileSyncTargetTree({ tenantId, userId })
  const spaces = groups.flatMap((group) => group.spaces)
  const hasReachableTarget = spaces.some((space) => space.selectable || space.has_children)
  const displayMatchesValue = Boolean(
    display
      && display.knowledge_id === value.knowledge_id
      && (display.folder_id ?? null) === value.folder_id
  )

  return (
    <div className="space-y-2 rounded-md border p-2">
      <div className="flex gap-2">
        <Input
          value={keyword}
          placeholder={t("system.developerToken.fileSync.spaceSearchPlaceholder")}
          onChange={(event) => setKeyword(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") onSearchSpaces(keyword.trim())
          }}
        />
        <Button type="button" variant="outline" onClick={() => onSearchSpaces(keyword.trim())}>
          {t("system.developerToken.fileSync.searchSpace")}
        </Button>
      </div>

      {displayMatchesValue && display?.stale && (
        <p className="text-xs text-destructive">
          {t("system.developerToken.fileSync.targetTree.stale")}
        </p>
      )}
      {displayMatchesValue && display && !display.stale && (
        <p className="text-xs text-muted-foreground">
          {formatDisplayPath(display, t("system.developerToken.fileSync.targetTree.root"))}
        </p>
      )}
      {loading && <TreeState text={t("system.developerToken.fileSync.targetTree.loading")} />}
      {!loading && error && (
        <TreeState text={t("system.developerToken.fileSync.targetTree.error")} error />
      )}
      {!loading && !error && groups.length === 0 && keyword.trim() && (
        <TreeState text={t("system.developerToken.fileSync.targetTree.empty")} />
      )}
      {!loading && !error && (
        (groups.length === 0 && !keyword.trim())
        || (groups.length > 0 && !hasReachableTarget)
      ) && (
        <TreeState text={t("system.developerToken.fileSync.targetTree.noPermission")} />
      )}

      {!loading && !error && groups.map((group) => (
        <section key={group.space_type} className="space-y-1">
          <div className="text-xs font-medium text-muted-foreground">
            {t(`system.developerToken.fileSync.targetTree.groups.${group.space_type}`)}
          </div>
          {group.spaces.map((space) => {
            const branch = tree.getBranch(space.id)
            return (
              <div key={space.id} className="space-y-1">
                <TargetRow
                  name={space.name}
                  selectable={space.selectable}
                  selected={value.knowledge_id === space.id && value.folder_id == null}
                  hasChildren={space.has_children}
                  expanded={branch?.expanded || false}
                  detail={space.selectable
                    ? t("system.developerToken.fileSync.targetTree.root")
                    : t("system.developerToken.fileSync.targetTree.navigationOnly")}
                  onToggle={() => tree.toggleBranch(space.id)}
                  onSelect={() => onChange({ knowledge_id: space.id, folder_id: null })}
                />
                {branch?.expanded && (
                  <FolderBranch
                    knowledgeId={space.id}
                    parentId={undefined}
                    depth={1}
                    value={value}
                    tree={tree}
                    onChange={onChange}
                  />
                )}
              </div>
            )
          })}
        </section>
      ))}
    </div>
  )
}

interface FolderBranchProps {
  knowledgeId: number
  parentId?: number
  depth: number
  value: TargetValue
  tree: ReturnType<typeof useDeveloperTokenFileSyncTargetTree>
  onChange: (value: TargetValue) => void
}

function FolderBranch({
  knowledgeId,
  parentId,
  depth,
  value,
  tree,
  onChange,
}: FolderBranchProps) {
  const { t } = useTranslation()
  const branch = tree.getBranch(knowledgeId, parentId)
  if (!branch) return null
  return (
    <div className="space-y-1">
      {branch.items.map((folder) => (
        <FolderNode
          key={folder.id}
          folder={folder}
          knowledgeId={knowledgeId}
          depth={depth}
          value={value}
          tree={tree}
          onChange={onChange}
        />
      ))}
      {branch.loading && (
        <TreeState text={t("system.developerToken.fileSync.targetTree.loadingChildren")} />
      )}
      {branch.error && (
        <TreeState text={t("system.developerToken.fileSync.targetTree.childrenError")} error />
      )}
      {branch.hasMore && !branch.loading && (
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => tree.loadMore(knowledgeId, parentId)}
        >
          {t("system.developerToken.fileSync.targetTree.loadMore")}
        </Button>
      )}
    </div>
  )
}

function FolderNode({
  folder,
  knowledgeId,
  depth,
  value,
  tree,
  onChange,
}: {
  folder: DeveloperTokenFileSyncTargetFolderOption
  knowledgeId: number
  depth: number
  value: TargetValue
  tree: ReturnType<typeof useDeveloperTokenFileSyncTargetTree>
  onChange: (value: TargetValue) => void
}) {
  const { t } = useTranslation()
  const branch = tree.getBranch(knowledgeId, folder.id)
  return (
    <div className="space-y-1" style={{ paddingLeft: `${depth * 16}px` }}>
      <TargetRow
        name={folder.name}
        selectable={folder.selectable}
        selected={value.knowledge_id === knowledgeId && value.folder_id === folder.id}
        hasChildren={folder.has_children}
        expanded={branch?.expanded || false}
        detail={!folder.selectable
          ? t("system.developerToken.fileSync.targetTree.navigationOnly")
          : undefined}
        onToggle={() => tree.toggleBranch(knowledgeId, folder.id)}
        onSelect={() => onChange({ knowledge_id: knowledgeId, folder_id: folder.id })}
      />
      {branch?.expanded && (
        <FolderBranch
          knowledgeId={knowledgeId}
          parentId={folder.id}
          depth={depth + 1}
          value={value}
          tree={tree}
          onChange={onChange}
        />
      )}
    </div>
  )
}

function TargetRow({
  name,
  selectable,
  selected,
  hasChildren,
  expanded,
  detail,
  onToggle,
  onSelect,
}: {
  name: string
  selectable: boolean
  selected: boolean
  hasChildren: boolean
  expanded: boolean
  detail?: string
  onToggle: () => void
  onSelect: () => void
}) {
  return (
    <div className="flex items-center gap-2 text-sm">
      {hasChildren ? (
        <button type="button" aria-label={name} onClick={onToggle} className="w-5">
          {expanded ? "−" : "+"}
        </button>
      ) : <span className="w-5" />}
      <input
        type="radio"
        aria-label={name}
        checked={selected}
        disabled={!selectable}
        onChange={onSelect}
      />
      <span>{name}</span>
      {detail && <span className="text-xs text-muted-foreground">{detail}</span>}
    </div>
  )
}

function TreeState({ text, error = false }: { text: string; error?: boolean }) {
  return <p className={`text-xs ${error ? "text-destructive" : "text-muted-foreground"}`}>{text}</p>
}

function formatDisplayPath(
  display: DeveloperTokenFileSyncTargetDisplay,
  rootLabel: string,
): string {
  const segments = [display.knowledge_name || String(display.knowledge_id)]
  if (display.target_type === "root") segments.push(rootLabel)
  else segments.push(...display.folder_path.map((item) => item.name))
  return segments.join(" / ")
}
