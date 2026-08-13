import { Button } from "@bisheng/ui";
import type { ComponentProps } from "react";
import { useEffect, useMemo, useState } from "react";
import type { ResourceType, SelectedSubject, SubjectType } from "~/api/permission";
import { Checkbox } from "~/components/ui/Checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "~/components/ui/Dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "~/components/ui/Tabs";
import { useLocalize } from "~/hooks";
import {
  INCLUDE_CHILDREN_CHECKBOX_CLASS,
  INCLUDE_CHILDREN_LABEL_CLASS,
  PERMISSION_DIALOG_CONTENT_CLASS,
  PERMISSION_FOOTER_LABEL_CLASS,
  SUBJECT_TAB_LIST_CLASS,
  SUBJECT_TAB_TRIGGER_CLASS,
} from "./permissionDialogStyles";
import { RelationSelect, type RelationModelOption } from "./RelationSelect";
import { SubjectSearchDepartment } from "./SubjectSearchDepartment";
import { SubjectSearchUser } from "./SubjectSearchUser";
import { SubjectSearchUserGroup } from "./SubjectSearchUserGroup";
import type { PermissionDraftRow } from "./usePermissionDraft";

export interface PermissionDraftSearchApi {
  grantUsersApi?: ComponentProps<typeof SubjectSearchUser>["grantUsersApi"];
  grantDepartmentChildrenApi?: ComponentProps<typeof SubjectSearchDepartment>["grantDepartmentChildrenApi"];
  grantDepartmentSearchApi?: ComponentProps<typeof SubjectSearchDepartment>["grantDepartmentSearchApi"];
  grantUserGroupsApi?: ComponentProps<typeof SubjectSearchUserGroup>["grantUserGroupsApi"];
}

export interface PermissionDraftPickerDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mode: "create" | "resource";
  resourceType: ResourceType;
  resourceId?: string;
  disabledIds: Record<SubjectType, number[]>;
  relationModels: RelationModelOption[];
  canAddNonUserSubjects: boolean;
  onConfirm: (rows: PermissionDraftRow[]) => void;
  searchApi?: PermissionDraftSearchApi;
}

export function PermissionDraftPickerDialog({
  open,
  onOpenChange,
  mode,
  resourceType,
  resourceId,
  disabledIds,
  relationModels,
  canAddNonUserSubjects,
  onConfirm,
  searchApi,
}: PermissionDraftPickerDialogProps) {
  const localize = useLocalize();
  const [subjectType, setSubjectType] = useState<SubjectType>("user");
  const [subjects, setSubjects] = useState<SelectedSubject[]>([]);
  const [includeChildren, setIncludeChildren] = useState(true);
  const [selectedModelId, setSelectedModelId] = useState("");
  const selectableModels = useMemo(
    () => subjectType === "user"
      ? relationModels
      : relationModels.filter((model) => model.relation !== "owner"),
    [relationModels, subjectType],
  );
  const activeModel = selectableModels.find((model) => model.id === selectedModelId)
    ?? selectableModels.find((model) => model.relation === "viewer")
    ?? selectableModels[0];

  useEffect(() => {
    if (!open) {
      setSubjects([]);
      setSubjectType("user");
      setIncludeChildren(true);
      setSelectedModelId("");
    }
  }, [open]);

  const handleSubjectTypeChange = (value: string) => {
    setSubjectType(value as SubjectType);
    setSubjects([]);
    setIncludeChildren(true);
    setSelectedModelId("");
  };

  const handleConfirm = () => {
    if (!activeModel || subjects.length === 0) return;
    onConfirm(subjects.map((subject) => ({
      subjectType: subject.type,
      subjectId: subject.id,
      subjectName: subject.name,
      relation: activeModel.relation,
      modelId: activeModel.id,
      includeChildren: subject.type === "department" ? includeChildren : undefined,
    })));
    onOpenChange(false);
  };

  const searchProps = {
    mode,
    resourceType,
    resourceId,
    value: subjects,
    onChange: setSubjects,
    disabledIds: disabledIds[subjectType],
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={PERMISSION_DIALOG_CONTENT_CLASS}>
        <DialogHeader className="shrink-0 text-left">
          <DialogTitle className="text-left">
            {localize("com_unified_permission.add_authorization")}
          </DialogTitle>
        </DialogHeader>
        <Tabs
          value={subjectType}
          onValueChange={handleSubjectTypeChange}
          className="mt-4 flex min-h-0 flex-1 flex-col overflow-hidden"
        >
          <div className="flex items-center gap-3">
            <TabsList className={SUBJECT_TAB_LIST_CLASS}>
              <TabsTrigger value="user" className={SUBJECT_TAB_TRIGGER_CLASS}>
                {localize("com_permission.subject_user")}
              </TabsTrigger>
              <TabsTrigger
                value="department"
                className={SUBJECT_TAB_TRIGGER_CLASS}
                disabled={!canAddNonUserSubjects}
              >
                {localize("com_permission.subject_department")}
              </TabsTrigger>
              <TabsTrigger
                value="user_group"
                className={SUBJECT_TAB_TRIGGER_CLASS}
                disabled={!canAddNonUserSubjects}
              >
                {localize("com_permission.subject_user_group")}
              </TabsTrigger>
            </TabsList>
            {subjectType === "department" && (
              <label className={INCLUDE_CHILDREN_LABEL_CLASS}>
                <Checkbox
                  className={INCLUDE_CHILDREN_CHECKBOX_CLASS}
                  checked={includeChildren}
                  onCheckedChange={(checked) => setIncludeChildren(checked === true)}
                />
                {localize("com_permission.include_children")}
              </label>
            )}
          </div>
          <TabsContent value="user" className="mt-3 min-h-0 flex-1 overflow-hidden p-0">
            <SubjectSearchUser {...searchProps} grantUsersApi={searchApi?.grantUsersApi} />
          </TabsContent>
          <TabsContent value="department" className="mt-3 min-h-0 flex-1 overflow-hidden p-0">
            <SubjectSearchDepartment
              {...searchProps}
              includeChildren={includeChildren}
              grantDepartmentChildrenApi={searchApi?.grantDepartmentChildrenApi}
              grantDepartmentSearchApi={searchApi?.grantDepartmentSearchApi}
            />
          </TabsContent>
          <TabsContent value="user_group" className="mt-3 min-h-0 flex-1 overflow-hidden p-0">
            <SubjectSearchUserGroup {...searchProps} grantUserGroupsApi={searchApi?.grantUserGroupsApi} />
          </TabsContent>
        </Tabs>
        <DialogFooter className="mt-3 shrink-0 items-center border-t pt-3 sm:justify-between">
          <div className="flex items-center gap-2">
            <span className={PERMISSION_FOOTER_LABEL_CLASS}>
              {localize("com_permission.uniform_grant")}
            </span>
            <RelationSelect
              value={activeModel?.id ?? ""}
              onChange={setSelectedModelId}
              options={selectableModels}
              disabled={selectableModels.length === 0}
              className="w-[132px]"
            />
          </div>
          <div className="flex gap-2">
            <Button color="default" variant="outlined" size="medium" onClick={() => onOpenChange(false)}>
              {localize("com_unified_permission.cancel")}
            </Button>
            <Button
              color="primary"
              variant="solid"
              size="medium"
              disabled={subjects.length === 0 || !activeModel}
              onClick={handleConfirm}
            >
              {localize("com_unified_permission.add_authorization")}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
