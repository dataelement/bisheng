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
  parent_folder_id?: number | null
}

interface DeveloperTokenFileSyncTargetTreeProps {
  tenantId: number
  userId: number
  groups: DeveloperTokenFileSyncTargetSpaceGroup[]
  value: TargetValue
  display: DeveloperTokenFileSyncTargetDisplay | null
  folderMode?: "none" | "fixed" | "dynamic"
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
  folderMode = "fixed",
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
      && (display.folder_id ?? null) === (folderMode === "fixed" ? value.folder_id : value.parent_folder_id ?? null)
  )

  const isRootSelected = (spaceId: number) => (
    value.knowledge_id === spaceId
    && (folderMode === "fixed"
      ? value.folder_id == null
      : folderMode === "dynamic"
        ? value.parent_folder_id == null
        : value.folder_id == null)
  )

  const handleSelectRoot = (spaceId: number) => {
    if (folderMode === "dynamic") {
      onChange({ knowledge_id: spaceId, folder_id: null, parent_folder_id: null })
      return
    }
    onChange({ knowledge_id: spaceId, folder_id: null })
  }

  const handleSelectFolder = (spaceId: number, folderId: number) => {
    if (folderMode === "dynamic") {
      onChange({ knowledge_id: spaceId, folder_id: null, parent_folder_id: folderId })
      return
    }
    onChange({ knowledge_id: spaceId, folder_id: folderId })
  }

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
                  selectable={space.selectable || folderMode === "none"}
                  selected={isRootSelected(space.id)}
                  hasChildren={space.has_children}
                  expanded={branch?.expanded || false}
                  detail={space.selectable
                    ? t("system.developerToken.fileSync.targetTree.root")
                    : t("system.developerToken.fileSync.targetTree.navigationOnly")}
                  onToggle={() => tree.toggleBranch(space.id)}
                  onSelect={() => handleSelectRoot(space.id)}
                />
                {branch?.expanded && (
                  <FolderBranch
                    knowledgeId={space.id}
                    parentId={undefined}
                    depth={1}
                    value={value}
                    folderMode={folderMode}
                    tree={tree}
                    onSelectRoot={handleSelectRoot}
                    onSelectFolder={handleSelectFolder}
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
  folderMode: "none" | "fixed" | "dynamic"
  tree: ReturnType<typeof useDeveloperTokenFileSyncTargetTree>
  onSelectRoot: (spaceId: number) => void
  onSelectFolder: (spaceId: number, folderId: number) => void
}

function FolderBranch({
  knowledgeId,
  parentId,
  depth,
  value,
  folderMode,
  tree,
  onSelectRoot,
  onSelectFolder,
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
          folderMode={folderMode}
          tree={tree}
          isSelected={value.knowledge_id === knowledgeId && (
            folderMode === "fixed"
              ? value.folder_id === folder.id
              : folderMode === "dynamic"
                ? value.parent_folder_id === folder.id
                : false
          )}
          onSelectFolder={onSelectFolder}
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
  folderMode,
  tree,
  isSelected,
  onSelectFolder,
}: {
  folder: DeveloperTokenFileSyncTargetFolderOption
  knowledgeId: number
  depth: number
  value: TargetValue
  folderMode: "none" | "fixed" | "dynamic"
  tree: ReturnType<typeof useDeveloperTokenFileSyncTargetTree>
  isSelected: boolean
  onSelectFolder: (spaceId: number, folderId: number) => void
}) {
  const { t } = useTranslation()
  const branch = tree.getBranch(knowledgeId, folder.id)
  const selectable = folderMode !== "none" && folder.selectable
  return (
    <div className="space-y-1" style={{ paddingLeft: `${depth * 16}px` }}>
      <TargetRow
        name={folder.name}
        selectable={selectable}
        selected={isSelected}
        hasChildren={folder.has_children}
        expanded={branch?.expanded || false}
        detail={!selectable
          ? t("system.developerToken.fileSync.targetTree.navigationOnly")
          : undefined}
        onToggle={() => tree.toggleBranch(knowledgeId, folder.id)}
        onSelect={() => onSelectFolder(knowledgeId, folder.id)}
      />
      {branch?.expanded && (
        <FolderBranch
          knowledgeId={knowledgeId}
          parentId={folder.id}
          depth={depth + 1}
          value={value}
          folderMode={folderMode}
          tree={tree}
          onSelectRoot={() => undefined}
          onSelectFolder={onSelectFolder}
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
