/** 浏览器里替代 node:fs/promises.

Node 26 的 esbuild 会把 polyfill 文件路径再拼上 /promises, 预构建 @dicebear/core 时读不到那个路径.
头像下载走浏览器的 a 标签, 不会调用这里.
*/
export async function writeFile(): Promise<void> {
  return undefined
}
