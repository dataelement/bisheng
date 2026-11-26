import { useLazyResourceActions } from "@/components/bs-comp/permission/useResourceActions";
import { AppNumType } from "@/types/app";
import { notification } from "@bisheng/ui";
import { useTranslation } from "react-i18next";

const APP_ACTIONS = ["visible", "edit", "publish", "unpublish", "delete", "manage_permission"];

interface AppActionTarget {
  id: string | number;
  flow_type?: number;
}

/** A card fetches only its own resource type when the user opens an action. */
export function useBuildAppActions() {
  const { t } = useTranslation("permission");
  const workflow = useLazyResourceActions("workflow", APP_ACTIONS);
  const assistant = useLazyResourceActions("assistant", APP_ACTIONS);
  const app = useLazyResourceActions("app", APP_ACTIONS);
  const bucket = (item: AppActionTarget) => item.flow_type === AppNumType.HOSTED_APP
    ? app : item.flow_type === AppNumType.ASSISTANT ? assistant : workflow;
  const load = async (item: AppActionTarget) => {
    const result = await bucket(item).load(String(item.id));
    if (result.hasError) notification.open({ type: "error", description: t("error.checkFailed") });
    return result;
  };
  return {
    load,
    can: (item: AppActionTarget, action: string) => bucket(item).actions[String(item.id)]?.includes(action) ?? false,
    loading: (item: AppActionTarget) => bucket(item).loading[String(item.id)] ?? false,
    error: (item: AppActionTarget) => bucket(item).errors[String(item.id)] ?? false,
    actions: (item: AppActionTarget) => bucket(item).actions[String(item.id)],
  };
}
