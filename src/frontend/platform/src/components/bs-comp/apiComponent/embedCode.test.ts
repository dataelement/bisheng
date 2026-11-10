import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { buildEmbedCode } from './embedCode'

const publicDir = resolve(__dirname, '../../../../public')
const origin = 'https://bisheng.example.com'

function attr(code: string, name: string): string | undefined {
  return code.match(new RegExp(`${name}="([^"]*)"`))?.[1]
}

describe.each([
  { label: 'root deployment', baseUrl: '' },
  { label: 'sub-path deployment', baseUrl: '/custom' },
])('buildEmbedCode on $label', ({ baseUrl }) => {
  const chatUrl = `${origin}${baseUrl}/workspace/chat/flow/app-1`

  it('script style points the loader and both icons at files under the base path', () => {
    const code = buildEmbedCode({ style: 'script', chatUrl, origin, baseUrl })

    expect(attr(code, 'src')).toBe(`${origin}${baseUrl}/iframe.js`)
    expect(attr(code, 'data-bot-src')).toBe(chatUrl)
    expect(attr(code, 'data-open-icon')).toBe(`${origin}${baseUrl}/assets/user.png`)
    expect(attr(code, 'data-close-icon')).toBe(`${origin}${baseUrl}/assets/bisheng/logo-small-dark.png`)
  })

  it('script style only references files that platform/public ships', () => {
    const code = buildEmbedCode({ style: 'script', chatUrl, origin, baseUrl })
    const publicRoot = `${origin}${baseUrl}`
    for (const name of ['src', 'data-open-icon', 'data-close-icon']) {
      const relative = attr(code, name)!.slice(publicRoot.length)
      expect(existsSync(resolve(publicDir, `.${relative}`)), `${name} -> ${relative}`).toBe(true)
    }
  })

  it('iframe style frames the chat link', () => {
    const code = buildEmbedCode({ style: 'iframe', chatUrl, origin, baseUrl })

    expect(code.startsWith('<iframe')).toBe(true)
    expect(attr(code, 'src')).toBe(chatUrl)
  })
})
