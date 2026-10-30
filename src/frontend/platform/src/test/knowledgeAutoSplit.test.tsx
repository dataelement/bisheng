import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import RuleFile from '@/pages/KnowledgePage/components/RuleFile'
vi.mock('@/pages/KnowledgePage/components/FileUploadSplitStrategy',()=>({default:()=>null}))
it('only exposes length and overlap for custom splitting', () => {
 const props = { rules: { split_mode: 'auto',chunk_size:1000,chunk_overlap:0 },fileList:[],setRules:vi.fn() }
 const view=render(<RuleFile {...props} />)
 expect(screen.queryByText('splitLength')).toBeNull()
 expect(screen.queryByText('chunkOverlap')).toBeNull()
 view.rerender(<RuleFile {...props} rules={{...props.rules,split_mode:'custom'}} />)
 expect(screen.getByText('splitLength')).toBeVisible()
 expect(screen.getByText('chunkOverlap')).toBeVisible()
})
