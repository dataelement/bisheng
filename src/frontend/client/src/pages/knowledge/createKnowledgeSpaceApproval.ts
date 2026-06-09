import {
    submitShougangKnowledgeSpaceCreateApprovalApi,
    type ShougangApprovalSubmitResult,
    type ShougangKnowledgeSpaceCreateApprovalPayload,
} from "~/api/approval";
import { createSpaceApi, SpaceLevel, VisibilityType } from "~/api/knowledge";
import type { CreateKnowledgeSpaceFormData } from "./CreateKnowledgeSpaceDrawer";

export function mapCreateFormToShougangApprovalPayload(
    form: CreateKnowledgeSpaceFormData,
): ShougangKnowledgeSpaceCreateApprovalPayload {
    const authType =
        form.joinPolicy === "public"
            ? VisibilityType.PUBLIC
            : form.joinPolicy === "review"
                ? VisibilityType.APPROVAL
                : VisibilityType.PRIVATE;

    return {
        name: form.name,
        description: form.description,
        auth_type: authType,
        is_released: form.publishToSquare === "yes",
        space_level: form.spaceLevel,
        department_id: form.departmentId,
        auto_tag_enabled: form.autoTagEnabled,
        auto_tag_library_id: form.autoTagLibraryId,
        auto_tag_custom_tags: form.autoTagCustomTags,
        reason: form.reason,
    };
}

export async function submitKnowledgeSpaceCreateWithApproval(
    form: CreateKnowledgeSpaceFormData,
): Promise<ShougangApprovalSubmitResult> {
    return submitShougangKnowledgeSpaceCreateApprovalApi(
        mapCreateFormToShougangApprovalPayload(form),
    );
}

export async function submitKnowledgeSpaceCreate(
    form: CreateKnowledgeSpaceFormData,
): Promise<ShougangApprovalSubmitResult> {
    if (form.spaceLevel === SpaceLevel.PERSONAL) {
        const space = await createSpaceApi({
            name: form.name,
            description: form.description,
            auth_type: VisibilityType.PRIVATE,
            is_released: false,
            space_level: form.spaceLevel,
            auto_tag_enabled: form.autoTagEnabled,
            auto_tag_library_id: form.autoTagLibraryId,
            auto_tag_custom_tags: form.autoTagCustomTags,
        });
        return {
            decision: "created",
            created: true,
            space,
        };
    }

    return submitKnowledgeSpaceCreateWithApproval(form);
}
