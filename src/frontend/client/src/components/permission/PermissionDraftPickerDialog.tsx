import { Button, Radio, RadioGroup } from "@bisheng/ui";
import type { ComponentProps } from "react";
import { useEffect, useMemo, useState } from "react";
import type { ResourceType, SelectedSubject, SubjectType } from "~/api/permission";
import { Checkbox } from "~/components/ui/Checkbox";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "~/components/ui/Dialog";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";
import {
  INCLUDE_CHILDREN_CHECKBOX_CLASS,
  INCLUDE_CHILDREN_LABEL_CLASS,
  PERMISSION_DIALOG_CONTENT_CLASS,
  PERMISSION_FOOTER_ACTIONS_CLASS,
  PERMISSION_FOOTER_LABEL_CLASS,
} from "./permissionDialogStyles";
import { RelationSelect, type RelationModelOption } from "./RelationSelect";
import { SubjectSearchDepartment } from "./SubjectSearchDepartment";
import { SubjectSearchUser } from "./SubjectSearchUser";
import { SubjectSearchUserGroup } from "./SubjectSearchUserGroup";
import type { PermissionDraftRow } from "./usePermissionDraft";

export interface PermissionDraftSearchApi {
  usersApi?: ComponentProps<typeof SubjectSearchUser>["usersApi"];
  departmentChildrenApi?: ComponentProps<typeof SubjectSearchDepartment>["departmentChildrenApi"];
  departmentSearchApi?: ComponentProps<typeof SubjectSearchDepartment>["departmentSearchApi"];
  userGroupsApi?: ComponentProps<typeof SubjectSearchUserGroup>["userGroupsApi"];
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
  const selectableModels = useMemo(() => relationModels, [relationModels]);
  const activeModel = selectableModels.find((model) => model.id === selectedModelId)
    ?? selectableModels.find((model) => model.level === 1)
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
      modelKey: activeModel.id,
      modelName: activeModel.name,
      modelLevel: activeModel.level,
      includeChildren: subject.type === "department" ? includeChildren : undefined,
    })));
    onOpenChange(false);
  };

  const searchProps = {
    mode,
    resourceType,
    resourceId: resourceId ?? "__creation__",
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
        <div className="mt-4 flex min-h-0 flex-1 flex-col overflow-hidden">
          <div className="flex items-center gap-3">
            <RadioGroup
              variant="button"
              value={subjectType}
              aria-label={localize("com_unified_permission.authorization")}
              onValueChange={handleSubjectTypeChange}
            >
              <Radio value="user">
                {localize("com_permission.subject_user")}
              </Radio>
              <Radio
                value="department"
                disabled={!canAddNonUserSubjects}
              >
                {localize("com_permission.subject_department")}
              </Radio>
              <Radio
                value="user_group"
                disabled={!canAddNonUserSubjects}
              >
                {localize("com_permission.subject_user_group")}
              </Radio>
            </RadioGroup>
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
          {/* The subject type is picked by the RadioGroup above, so the panes
              render conditionally — there is no Tabs shell to hang them on. */}
          <div className="mt-3 min-h-0 flex-1 overflow-hidden">
            {subjectType === "user" && (
              <SubjectSearchUser {...searchProps} usersApi={searchApi?.usersApi} />
            )}
            {subjectType === "department" && (
              <SubjectSearchDepartment
                {...searchProps}
                includeChildren={includeChildren}
                departmentChildrenApi={searchApi?.departmentChildrenApi}
                departmentSearchApi={searchApi?.departmentSearchApi}
              />
            )}
            {subjectType === "user_group" && (
              <SubjectSearchUserGroup {...searchProps} userGroupsApi={searchApi?.userGroupsApi} />
            )}
          </div>
        </div>
        {/* Mobile stacks the relation picker above a full-width action pair, with
            the divider directly above the buttons — matching the resource grant
            dialog. Desktop keeps both on one bordered row. */}
        <div className="mt-3 flex shrink-0 flex-col gap-3 min-[769px]:flex-row min-[769px]:items-center min-[769px]:justify-between min-[769px]:border-t min-[769px]:pt-3">
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
          <div
            className={cn(
              "max-[768px]:border-t max-[768px]:pt-3",
              PERMISSION_FOOTER_ACTIONS_CLASS,
            )}
          >
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
        </div>
      </DialogContent>
    </Dialog>
  );
}
