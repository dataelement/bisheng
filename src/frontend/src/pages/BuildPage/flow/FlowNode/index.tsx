import { Badge } from '@/components/bs-ui/badge';
import { Input, Textarea } from '@/components/bs-ui/input';
import EditTitle from '@/components/bs-ui/input/editTitle';
import { Label } from '@/components/bs-ui/label';
import { cn } from '@/utils';
import { House } from 'lucide-react';
import { useCallback } from 'react';
import { Handle, NodeToolbar, Position } from 'reactflow';
import NodeToolbarComponent from './NodeToolbarComponent';
import Parameter from './Parameter';
import ParameterGroup from './ParameterGroup';


function CustomNode({ data, selected, isConnectable }) {
    const onChange = useCallback((evt) => {
        console.log(evt.target.value);
    }, []);

    console.log('data :>> ', data);

    return (
        <div>
            {/* head bars */}
            <NodeToolbar align="end">
                <NodeToolbarComponent></NodeToolbarComponent>
            </NodeToolbar>

            <div className={cn("bisheng-node border-2", selected ? "active" : "")}>
                {/* head */}
                <div className='p-4 bisheng-node-head'>
                    <div className='relative z-10 flex gap-2'>
                        <House className='text-blue-700' />
                        <EditTitle str="开始" className={'text-background'} onChange={() => { }}>
                            {(val) => <p className='text-gray-50 font-bold'>{val}</p>}
                        </EditTitle>
                    </div>
                </div>
                <p className='text-xs p-2 bg-background text-muted-foreground'>程池内同步任务是否会阻塞，导致性能差，减少同步任务对性能的影响</p>
                {/* body */}
                <div className='px-4 pb-4 border-b-8 border-background'>
                    <Badge className='my-2'>开场引导</Badge>
                    <div className='item'>
                        <Label className='bisheng-label'>开场白</Label>
                        <Textarea></Textarea>
                    </div>
                    <div className='item'>
                        <Label className='bisheng-label'>引导问题</Label>
                        <Input></Input>
                    </div>
                </div>
                <div className='px-4 pb-4 border-b-8 border-background'>
                    <Badge className='my-2'>开场引导</Badge>
                    <div className='item'>
                        <Label className='bisheng-label'>开场白</Label>
                        <Textarea></Textarea>
                    </div>
                    <div className='item'>
                        <Label className='bisheng-label'>引导问题</Label>
                        <Input></Input>
                    </div>
                </div>
                {/* footer */}
                <Handle
                    id="a"
                    type="target"
                    position={Position.Left}
                    className='bisheng-flow-handle'
                    style={{left: -8}}
                />
                <Handle
                    id="b"
                    type="source"
                    position={Position.Right}
                    className='bisheng-flow-handle'
                    style={{right: -8}}
                />
            </div>
        </div>
    );
}

export default CustomNode;
