import { opendir } from 'node:fs/promises';
import { homedir } from 'node:os';
import path from 'node:path';

/** Check the same optional Office font cache used by LibreOffice Kit before
 * document work starts. macOS owns the authorization prompt and decision.
 * Platform, home and filesystem dependencies are host-selected, never RPC input.
 */
export async function prepareOfficeFontAccess({platform=process.platform,home=homedir(),openDirectory=opendir}={}) {
  if(platform!=='darwin')return {status:'not-required'};
  const directory=path.posix.join(home,'Library','Group Containers','UBF8T346G9.Office','FontCache');
  let handle;
  try {
    handle=await openDirectory(directory);
    await handle.read();
    return {status:'ready'};
  } catch(error) {
    // Match the SDK's optional font-source handling; system fonts remain available.
    if(['ENOENT','ENOTDIR'].includes(error.code))return {status:'absent'};
    if(['EACCES','EPERM'].includes(error.code))return {status:'restricted'};
    throw error;
  } finally {
    await handle?.close();
  }
}
