// @vitest-environment jsdom

import { expect, it } from 'vitest';
import { annotationHtml } from './annotations';
it('preserves text formatting without allowing CSS declarations through values',()=>{
  const html=annotationHtml({name:'span',attributes:{style:{color:'red;position:fixed',fontSize:'12px'}},value:'<hello>'});
  expect(html).toContain('font-size:12px');expect(html).toContain('&lt;hello&gt;');
  expect(html).not.toContain('position');
});
