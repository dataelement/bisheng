import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import InputItem from './InputItem';
it('keeps dynamic numeric node bounds in the business handler',()=>{
    const change=vi.fn();render(<InputItem label="Count" type="number" data={{key:'count',value:2,min:1,max:5}} onChange={change}/>);
    const field=screen.getByRole('spinbutton');
    fireEvent.change(field,{target:{value:'6'}});expect(change).not.toHaveBeenCalled();
    fireEvent.change(field,{target:{value:'-1'}});expect(change).not.toHaveBeenCalled();
    fireEvent.change(field,{target:{value:'5'}});expect(change).toHaveBeenLastCalledWith(5);
});
