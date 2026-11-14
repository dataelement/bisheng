import axios from "@/controllers/request"
import {
  DocumentParseConfig,
  DocumentParseConfigResponse,
  DocumentParseTestResult,
} from "@/types/api/documentParse"

// Path deliberately says "settings", not "config": customer WAFs block URLs
// containing "config" as a sensitive-file probe (see test_route_path_naming.py).
export async function getDocumentParseConfigApi(): Promise<DocumentParseConfigResponse> {
  return await axios.get(`/api/v1/settings/document-parse`)
}

export async function saveDocumentParseConfigApi(data: DocumentParseConfig): Promise<void> {
  return await axios.post(`/api/v1/settings/document-parse`, data)
}

/** Probe the configured service without saving. Cheap: creates no parse job. */
export async function testDocumentParseConfigApi(
  data: DocumentParseConfig
): Promise<DocumentParseTestResult> {
  return await axios.post(`/api/v1/settings/document-parse/test`, data)
}
