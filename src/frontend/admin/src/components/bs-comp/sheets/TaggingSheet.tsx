import { useState } from "react";
import {
    Sheet,
    SheetContent,
    SheetTitle,
    SheetTrigger,
} from "../../bs-ui/sheet";
import { DragDropContext, Draggable, Droppable } from 'react-beautiful-dnd';

export default function TaggingSheet({children}) {
    const init = [
        {id:'01',name:'Button01'},
        {id:'02',name:'Button02'},
        {id:'03',name:'Button03'},
    ]
    const [buttons, setButtons] = useState(init)

    const handleDragEnd = (result) => {
        if(!result.destination) return
        const newButtons = buttons
        const [moveItem] = newButtons.splice(result.source.index, 1)
        newButtons.splice(result.destination.index, 0, moveItem)
        setButtons(newButtons)
    }

    return <Sheet>
        <SheetTrigger asChild>{children}</SheetTrigger>
        <SheetContent className="sm:min-w-[800px]">
            <SheetTitle>给助手打标签</SheetTitle>
            <div className="w-full h-full grid grid-cols-[80%,20%]">
                <div className="bg-slate-500">

                </div>
                <div className="bg-slate-300">
                    <DragDropContext onDragEnd={handleDragEnd}>
                        <Droppable droppableId={'list'}>
                            {(provided) => (
                                <div {...provided.droppableProps} ref={provided.innerRef}>
                                    {buttons.map((b,index) => (
                                        <Draggable key={'drag' + b.id} draggableId={'drag' + b.id} index={index}>
                                            {(provided) => (
                                                <div ref={provided.innerRef} {...provided.draggableProps} 
                                                {...provided.dragHandleProps}>
                                                {index + 1} + {b.name}
                                                </div>
                                        )}
                                    </Draggable>
                                    ))}
                                    {/* {provided.placeholder} */}
                                </div>
                            )}
                        </Droppable>
                    </DragDropContext>
                </div>
            </div>
        </SheetContent>
    </Sheet>
}