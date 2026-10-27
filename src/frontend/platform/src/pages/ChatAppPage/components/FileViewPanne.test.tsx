import { useEffect } from 'react';
import { fireEvent,render } from '@testing-library/react';
import { expect,it,vi } from 'vitest';
import FileViewPanne from './FileViewPanne';
const {mounts}=vi.hoisted(()=>({mounts:{count:0}}));
vi.mock('@/components/bs-comp/FileView',()=>({default:function MockPdfView({scrollTo}:{scrollTo?:number[]}){useEffect(()=>{mounts.count++;},[]);return <output>{JSON.stringify(scrollTo)}</output>;}}));
vi.mock('@/components/bs-ui/utils',()=>({generateUUID:()=>Math.random().toString()}));
vi.mock('@/pages/KnowledgePage/components/DocxFileViewer',()=>({default:()=>null}));
vi.mock('@/pages/KnowledgePage/components/TxtFileViewer',()=>({default:()=>null}));
it('keeps the PDF session mounted when selecting another legacy source paragraph',()=>{
 const file={fileUrl:'/fixture.pdf',fileName:'fixture.pdf',parse_type:'etl4lm',chunks:[{score:0.9,box:[{page:0,bbox:[10,20,100,40]}]},{score:0.8,box:[{page:1,bbox:[10,50,100,80]}]}]};
 const view=render(<FileViewPanne file={file}/>);expect(mounts.count).toBe(1);
 fireEvent.click(view.container.querySelectorAll('.flag')[1]);
 expect(view.getByRole('status').textContent).toBe('[1,50]');expect(mounts.count).toBe(1);
});
