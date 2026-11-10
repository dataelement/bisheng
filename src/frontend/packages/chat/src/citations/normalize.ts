import { asRecord } from '../core/normalizeHistory';
import type { ChatCitation, ChatCitationPayload } from './types';
export function parseLegacyWebCitationContent(content: string) {
  const raw=String(content||''); const match=raw.match(/:::web([\s\S]*?):::/);
  if(!match)return {content:raw,webContent:[] as ChatCitationPayload[]};
  let webContent: ChatCitationPayload[]=[];
  try { const value:unknown=JSON.parse(match[1].trim()||'[]'); if(Array.isArray(value))webContent=value.filter(item=>item&&typeof item==='object'); } catch { /* Malformed historical metadata has no sources. */ }
  return {content:raw.replace(/:::web[\s\S]*?:::/,'').trim(),webContent};
}
export function normalizeCitationItems(source?:unknown):ChatCitation[]|null {
  const value=asRecord(source);const message=asRecord(value.message);
  const list=[value.citations,value.citation_registry_items,message.citations,message.citation_registry_items].find(item=>Array.isArray(item)&&item.length);
  if(!Array.isArray(list))return null;
  const entries=list.filter(item=>item&&typeof item==='object'&&typeof item.citationId==='string').map(item=>({...item,type:typeof item.type==='string'?item.type:''})) as ChatCitation[];
  return entries.length?entries:null;
}
