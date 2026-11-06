import { expect, it } from 'vitest';
import { isNumberDraftWithinBounds } from './fieldValidation';
it('preserves editable empty drafts without accepting invalid numeric bounds',()=>{
    expect(isNumberDraftWithinBounds('',{min:1,max:1000,maxLength:6})).toBe(true);
    for(const value of ['-1','0','1001','1000000','NaN']) expect(isNumberDraftWithinBounds(value,{min:1,max:1000,maxLength:6})).toBe(false);
    expect(isNumberDraftWithinBounds('1000',{min:1,max:1000,maxLength:6})).toBe(true);
});
it('retains fractions for quota and temperature fields',()=>{
    expect(isNumberDraftWithinBounds('0.1',{min:0.1,max:2})).toBe(true);
    expect(isNumberDraftWithinBounds('2.1',{min:0.1,max:2})).toBe(false);
});
