// Build-time switch for web link upload only.
// Media upload is controlled at runtime via enable_media_upload from /api/v1/env.
export const knowledgeUploadCapabilities = {
    webLink: true,
} as const;
