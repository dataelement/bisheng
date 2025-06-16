import { cname } from "@/components/bs-ui/utils";
import { BookOpenTextIcon, Bot, Brain, Code2, FileDown, FileSearch, FlagTriangleRight, Hammer, Home, Keyboard, MessagesSquareIcon, Split, FileVolume, BookAudio } from "lucide-react";
export const Icons = {
    'start': Home,
    'input': Keyboard,
    'output': MessagesSquareIcon,
    'code': Code2,
    'llm': Brain,
    'rag': BookOpenTextIcon,
    'qa_retriever': FileSearch,
    'agent': Bot,
    'end': FlagTriangleRight,
    'condition': Split,
    'report': FileDown,
    'tts': FileVolume,
    'stt': BookAudio,
}
export const Colors = {
    'start': 'bg-[#FFD89A]',
    'input': 'bg-primary',
    'output': 'bg-primary',
    'code': 'bg-[#FFCABA]',
    'llm': 'bg-[#D9D7FF]',
    'rag': 'bg-[#BBDBFF]',
    'qa_retriever': 'bg-[#B8EEDF]',
    'agent': 'bg-[#FFD89A]',
    'end': 'bg-red-400',
    'condition': 'bg-[#EDC9E9]',
    'report': 'bg-[#9CE4F4]',
    'tts': 'bg-[#9CE4F4]',
    'stt': 'bg-[#FFCABA]',
}

export default function NodeLogo({ type, className = '', colorStr = '' }) {

    // tool special
    if (type === 'tool') {
        const keys = Object.keys(Colors)
        const _colorKey = keys[parseInt(colorStr.charCodeAt(0) + '', 16) % keys.length]
        return <div className={cname(`${Colors[_colorKey]} p-[5px] rounded-md dark:text-gray-600`, className)}><Hammer size={14} /></div>
    }

    const IconComp = Icons[type] || Hammer
    const color = Colors[type] || 'text-gray-950'
    return <div className={cname(`${color} dark:text-gray-600 ${['input', 'output'].includes(type) && 'text-[#fff] dark:text-[#fff]'} p-[5px] rounded-md`, className)}><IconComp size={14} /></div>
};
