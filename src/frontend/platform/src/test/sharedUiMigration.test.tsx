import { createRef } from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { Button, Input, Textarea, Toaster, Notifier, notification, toast } from '@bisheng/ui';
import { InputList } from '@/components/bs-comp/formFields/InputList';
import { NonNegativeInput } from '@/components/bs-comp/formFields/NonNegativeInput';
import { PassInput } from '@/components/bs-comp/formFields/PassInput';
import Temperature from '@/pages/BuildPage/assistant/editAssistant/Temperature';

afterEach(() => { cleanup(); toast.clear(); notification.closeAll(); vi.useRealTimers(); });
it('retains loading submission protection at the business caller', () => {
    const submit = vi.fn(), saving = true;
    render(<Button loading={saving} disabled={saving} onClick={submit}>Save</Button>);
    fireEvent.click(screen.getByRole('button', {name:'Save'}));
    expect(submit).not.toHaveBeenCalled();
});
it('uses shared soft limits and forwards refs', () => {
    const ref = createRef<HTMLInputElement>();
    render(<><Input ref={ref} aria-label="Name" maxLength={4} showCount defaultValue="Long name"/><Textarea aria-label="Notes" maxLength={4} showCount defaultValue="Long notes"/></>);
    expect(ref.current).not.toHaveAttribute('maxlength');
    expect(ref.current).toHaveAttribute('aria-invalid','true');
    expect(screen.getByRole('textbox',{name:'Notes'})).toHaveAttribute('aria-invalid','true');
});
it('retains numeric validation in the business field', () => {
    const change=vi.fn();render(<NonNegativeInput aria-label="Limit" min={1} max={4} defaultValue={2} onValueChange={change}/>);
    const input=screen.getByRole('spinbutton',{name:'Limit'});fireEvent.change(input,{target:{value:'8'}});
    // The shared InputNumber keeps what was typed and reports the range on blur.
    expect(input).toHaveValue('8');expect(change).not.toHaveBeenCalled();
    fireEvent.blur(input);expect(input).toHaveAttribute('aria-invalid','true');expect(screen.getByText('sharedUi.maximum')).toBeInTheDocument();
    fireEvent.change(input,{target:{value:'3'}});expect(change).toHaveBeenLastCalledWith(3);expect(input).not.toHaveAttribute('aria-invalid');
    fireEvent.change(input,{target:{value:''}});fireEvent.blur(input);expect(change).toHaveBeenLastCalledWith(2);expect(input).toHaveValue('2');
});
it('retains labeled secret visibility and its value', () => {
    render(<PassInput aria-label="Secret" defaultValue="secret"/>);const input=screen.getByLabelText('Secret');
    fireEvent.click(screen.getByRole('button'));expect(input).toHaveAttribute('type','text');expect(input).toHaveValue('secret');
});
it('retains dictionary identifiers and the temperature bounds', () => {
    const change=vi.fn();render(<InputList dict value={[{key:'preset',value:'First'}]} onChange={change}/>);
    fireEvent.change(screen.getByRole('textbox'),{target:{value:'Changed'}});expect(change.mock.calls[0][0][0]).toEqual({key:'preset',value:'Changed'});
    const temperature=vi.fn();render(<Temperature value={0} onChange={temperature}/>);
    const box=screen.getByRole('spinbutton',{name:'build.temperature'});
    expect(box).toHaveAttribute('aria-valuemin','0');expect(box).toHaveAttribute('aria-valuemax','2');
    expect(screen.getByRole('button',{name:'bs:sharedUi.decrease'})).toBeDisabled();
    fireEvent.change(box,{target:{value:'0.7'}});expect(temperature).toHaveBeenLastCalledWith(0.7);
    // An out-of-range value stays in the box and never reaches the business state.
    fireEvent.change(box,{target:{value:'3'}});expect(temperature).toHaveBeenCalledTimes(1);
});
it('uses direct shared queues with multiline descriptions and separate viewports',()=>{
    vi.useFakeTimers();render(<><Toaster closeLabel="Close"/><Notifier closeLabel="Close" expandLabel="Expand"/></>);
    let first='',second='',notice='';act(()=>{first=toast.show({type:'success',message:'Saved'});second=toast.show({type:'success',message:'Saved'});notice=notification.open({title:'Import',description:['Row 1 failed','Row 2 failed'].join('\n'),type:'error'});});
    expect(first).toBe(second);expect(screen.getByText(/Row 1 failed/)).toHaveTextContent('Row 2 failed');
    act(()=>{notification.close(notice);toast.dismiss(first);vi.advanceTimersByTime(300)});expect(screen.queryByText('Import')).toBeNull();
});
