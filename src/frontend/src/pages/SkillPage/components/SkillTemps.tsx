import { PlusSquare } from "lucide-react";
import { useNavigate } from "react-router-dom";
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle
} from "../../../components/ui/card";
import { gradients } from "../../../utils";
import { useTranslation } from "react-i18next";

export default function SkillTemps({ flows, isTemp = false,
    title = 'skills.skillTemplate',
    desc = 'skills.skillTemplateChoose',
    open, setOpen, onSelect }) {

    const { t } = useTranslation()
    const navigate = useNavigate()

    return <dialog className={`modal bg-blur-shared ${open ? 'modal-open' : 'modal-close'}`} onClick={() => setOpen(false)}>
        <form method="dialog" className="max-w-[80%] flex flex-col modal-box bg-[#fff] shadow-lg dark:bg-background" onClick={e => e.stopPropagation()}>
            <button className="btn btn-sm btn-circle btn-ghost absolute right-2 top-2" onClick={() => setOpen(false)}>✕</button>
            <h3 className="font-bold text-lg">{t(title)}</h3>
            <p className="py-4">{t(desc)}</p>
            <div className="flex flex-wrap overflow-y-auto no-scrollbar">
                {flows.map((el) => (
                    <Card key={el.id} className="w-[300px] mr-4 mb-4 overflow-hidden cursor-pointer" onClick={() => onSelect(el)}>
                        <CardHeader>
                            <CardTitle className=" flex items-center gap-2">
                                <div className={"rounded-full w-[30px] h-[30px] " + gradients[parseInt(el.id, 16) % gradients.length]}></div>
                                <span>{el.name}</span>
                            </CardTitle>
                            <CardDescription className="">{el.description}</CardDescription>
                        </CardHeader>
                    </Card>
                ))}
                {isTemp && <Card className="w-[300px] mr-4 mb-4 overflow-hidden cursor-pointer" onClick={() => navigate('/skill')}>
                    <CardContent className="flex flex-col items-center pt-4 hover:text-slate-500">
                        <PlusSquare />
                        <span>{t('skills.custom')}</span>
                    </CardContent>
                </Card>}
            </div>
        </form>
    </dialog>
};
