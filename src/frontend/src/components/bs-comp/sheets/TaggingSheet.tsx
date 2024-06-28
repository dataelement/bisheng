import {
    Sheet,
    SheetContent,
    SheetTitle,
    SheetTrigger,
} from "../../bs-ui/sheet";
import { DragDropContext, Draggable, Droppable } from 'react-beautiful-dnd';

export default function TaggingSheet({children}) {
    const buttons = [
        {id:'01',name:'Button01'},
        {id:'02',name:'Button02'},
        {id:'03',name:'Button03'},
    ]

    return <Sheet>
        <SheetTrigger asChild>{children}</SheetTrigger>
        <SheetContent className="bg-gray-100 sm:min-w-[800px]">
            <SheetTitle>给助手打标签</SheetTitle>
            <div className="w-full h-full grid grid-cols-[80%,20%]">
                <div className="bg-slate-500">

                </div>
                <div className="bg-slate-300">
                    <DragDropContext onDragEnd={() => console.log('-------------')}>
                        <Droppable droppableId={'list'}>
                            {(provided) => (
                                <div {...provided.droppableProps} ref={provided.innerRef}>
                                    {buttons.map((b,index) => (
                                        <Draggable key={'drag' + b.id} draggableId={'drag' + b.id} index={index}>
                                            {(provided) => (
                                                <div ref={provided.innerRef} {...provided.draggableProps} 
                                                {...provided.dragHandleProps}>
                                                {b.name}
                                                </div>
                                        )}
                                    </Draggable>
                                    ))}
                                </div>
                            )}
                        </Droppable>
                    </DragDropContext>
                </div>
            </div>
        </SheetContent>
    </Sheet>
}