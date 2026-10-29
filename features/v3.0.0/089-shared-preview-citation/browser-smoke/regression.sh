#!/usr/bin/env bash
# Run from the repository root with Node 20 and workspace dependencies installed.
set -euo pipefail
pnpm --dir src/frontend/packages/chat test
pnpm --dir src/frontend/packages/file-viewers test
pnpm --dir src/frontend/packages/diagram-runtime test
pnpm --dir src/frontend/packages/api-client test
pnpm --dir src/frontend test:config
pnpm --dir src/frontend/platform exec vitest run \
  src/pages/KnowledgePage/components/PreviewResult.test.tsx \
  src/pages/KnowledgePage/components/ExcelPreviewI18n.test.tsx \
  src/controllers/API/previewFileSplit.errors.test.ts \
  src/controllers/API/citationScope.test.ts \
  src/components/bs-comp/appChat \
  src/components/bs-comp/preview/PlatformPdfPreview.test.tsx \
  src/components/bs-comp/preview/pdfEditing.test.ts \
  src/components/bs-comp/chatComponent/CitationDocumentPreview.test.tsx \
  src/components/bs-comp/chatComponent/usePlatformCitationServices.test.tsx \
  src/pages/ChatAppPage/components/FileViewPanne.test.tsx \
  src/pages/LogPage/useAppLog/dailyChatDetail.test.tsx --maxWorkers=1 --minWorkers=1
pnpm --dir src/frontend/client exec jest \
  src/components/Chat/Messages/Content/CitationDocumentPreview.test.tsx \
  src/components/Chat/Messages/Content/citationLocate.test.ts \
  src/components/Chat/Messages/Content/useCitedPassageLocate.test.tsx \
  src/components/Linsight/Artifacts/ResultSection.test.tsx \
  src/components/Linsight/Artifacts/artifactUtils.test.ts \
  src/components/Linsight/Artifacts/citationUtils.bake.test.ts \
  src/components/Linsight/Artifacts/sourcePassages.test.ts \
  src/api/citationScope.test.ts src/api/citationErrorContract.test.ts \
  src/pages/knowledge/FilePreview/viewers/PdfViewer.errors.test.tsx \
  src/utils/sandboxedHtml.test.ts --runInBand --coverage=false
