import axios from "@/controllers/request";
import type {
  EPlusBindableSpace,
  EPlusBotConfig,
  EPlusBotConfigInput,
} from "@/types/eplus";

const assistantBotPath = (assistantId: string) =>
  `/api/v1/eplus/assistants/${encodeURIComponent(assistantId)}/bot`;

export async function getEPlusBotConfigApi(
  assistantId: string,
): Promise<EPlusBotConfig | null> {
  return await axios.get(assistantBotPath(assistantId));
}

export async function saveEPlusBotConfigApi(
  assistantId: string,
  data: EPlusBotConfigInput,
): Promise<EPlusBotConfig> {
  return await axios.put(assistantBotPath(assistantId), data);
}

export async function deleteEPlusBotConfigApi(assistantId: string): Promise<boolean> {
  return await axios.delete(assistantBotPath(assistantId));
}

export async function listEPlusBindableSpacesApi(
  assistantId: string,
): Promise<EPlusBindableSpace[]> {
  return await axios.get(`${assistantBotPath(assistantId)}/spaces`);
}
