import { useEffect, useMemo, useState } from "react"
import { useMessageStore } from "./messageStore"

// 引导词推荐
export default function GuideQuestions({ locked, chatId, questions, onClick }) {
    const [showGuideQuestion, setShowGuideQuestion] = useMessageStore(state => [state.showGuideQuestion, state.setShowGuideQuestion])

    const [show, setShow] = useState(false)
    useEffect(() => {
        questions.length && setShow(true)
    }, [chatId])

    const words = useMemo(() => {
        if (questions.length < 4) return questions
        // 随机按序取三个
        const res = []
        const randomIndex = Math.floor(Math.random() * questions.length)
        for (let i = 0; i < 3; i++) {
            const item = questions[(randomIndex + i) % (questions.length - 1)]
            res.push(item)
        }
        return res
    }, [questions])


    if (locked || !words.length) return null

    if (showGuideQuestion || show) return <div className="relative">
        <div className="absolute left-0 bottom-0">
            <p className="text-gray-950 text-sm mb-2 bg-[#fff] w-fit px-2 py-1">推荐问题</p>
            {
                words.map((question, index) => (
                    <div
                        key={index}
                        className="w-fit bg-[#d4dffa] shadow-md text-gray-600 rounded-md mb-2 px-4 py-1 text-sm cursor-pointer"
                        onClick={() => {
                            setShowGuideQuestion(false)
                            setShow(false);
                            onClick(question)
                        }}
                    >{question}</div>
                ))
            }
        </div>
    </div>


    return null
};
