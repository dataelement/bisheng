import { realpath } from 'node:fs/promises'
import path from 'node:path'

/** Resolve the effective directory without turning a directory change into a permission grant. */
export async function workspaceDirectory(ctx, exec, write = true) {
  if (!exec.agent?.session.header.cwd) throw new Error('PPTD tools require an active workspace')
  const policy = ctx.sandboxPolicy.resolve({ session: exec.agent.session })
  const allowed = write ? ['workspace-write', 'danger-full-access'] : ['read-only', 'workspace-write', 'danger-full-access']
  if (!allowed.includes(policy.mode)) throw new Error('PPTD tools require workspace write permission')
  const directory = await realpath(await ctx.workingDirectory.ensure(exec.agent, exec.signal))
  const root = await realpath(policy.workspaceRoot)
  const offset = path.relative(root, directory)
  if (policy.mode !== 'danger-full-access' && (offset === '..' || offset.startsWith(`..${path.sep}`) || path.isAbsolute(offset))) {
    throw new Error('PPTD directory must be covered by the session workspace policy')
  }
  exec.signal.throwIfAborted()
  return directory
}
