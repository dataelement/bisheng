import AceEditor from "react-ace";
// import "ace-builds/webpack-resolver";
import { useContext, useEffect, useRef, useState } from "react";
import { Button } from "../../components/bs-ui/button";
import BaseModal from "../baseModal";
import { BookMarked } from "lucide-react";
import { useTranslation } from "react-i18next";
import { alertContext } from "../../contexts/alertContext";

export default function DictAreaModal({
    children,
    onChange,
    value,
}): JSX.Element {
    const [open, setOpen] = useState(false);

    const codeRef = useRef(value);
    const validataRef = useRef([])

    const { t } = useTranslation()

    const { setErrorData } = useContext(alertContext);
    const handleCreate = () => {
        if (validataRef.current.length) return setErrorData({
            title: `${t('prompt')}:`,
            list: [t('model.jsonFormatError')]
        });
        onChange(codeRef.current)
        setOpen(false)
    }

    return (
        <BaseModal size="medium-h-full" open={open} setOpen={setOpen}>
            <BaseModal.Trigger>{children}</BaseModal.Trigger>
            <BaseModal.Header description={''}>
                <span className="pr-2">{t('code.editDictionary')}</span>
                <BookMarked
                    className="h-6 w-6 pl-1 text-primary "
                    aria-hidden="true"
                />
            </BaseModal.Header>
            <BaseModal.Content>
                <div className="flex h-full w-full flex-col transition-all ">
                    <AceEditor
                        value={codeRef.current || '{}'}
                        mode="json"
                        theme={"twilight"}
                        highlightActiveLine={true}
                        showPrintMargin={false}
                        fontSize={14}
                        showGutter
                        enableLiveAutocompletion
                        name="CodeEditor"
                        onChange={(value) => codeRef.current = value}
                        onValidate={(e) => validataRef.current = e}
                        className="h-[500px] w-full rounded-lg border-[1px] border-border custom-scroll"
                    />
                    <div className="flex h-fit w-full justify-end">
                        <Button
                            className="mt-3 rounded-full"
                            type="submit"
                            onClick={handleCreate}
                        >
                            {t('save')}
                        </Button>
                    </div>
                </div>
            </BaseModal.Content>
        </BaseModal>
    );
}