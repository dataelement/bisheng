import { describe, expect, it } from 'vitest'
import cn from '../../../packages/ui/src/utils/cn'

describe('shared semantic typography and color', () => {
    it.each(['text-white text-body', 'text-body text-white'])(
        'keeps tooltip contrast and font size together: %s', classes => {
            expect(cn(classes).split(' ')).toEqual(expect.arrayContaining(['text-white', 'text-body']))
        },
    )
    it('still resolves conflicting sizes and colors independently', () => {
        expect(cn('text-h1 text-danger', 'text-body text-white').split(' '))
            .toEqual(['text-body', 'text-white'])
    })
})
