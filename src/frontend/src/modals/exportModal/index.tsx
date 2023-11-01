import { Download } from "lucide-react";
import { useContext, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import EditFlowSettings from "../../components/EditFlowSettingsComponent";
import { Button } from "../../components/ui/button";
import { Checkbox } from "../../components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "../../components/ui/dialog";
import { alertContext } from "../../contexts/alertContext";
import { PopUpContext } from "../../contexts/popUpContext";
import { TabsContext } from "../../contexts/tabsContext";
import { removeApiKeys } from "../../utils";

export default function ExportModal() {
  const { t } = useTranslation()

  const [open, setOpen] = useState(true);
  const { closePopUp } = useContext(PopUpContext);

  const { setErrorData } = useContext(alertContext);
  const { flows, tabId, updateFlow, downloadFlow } =
    useContext(TabsContext);

  function setModalOpen(x: boolean) {
    setOpen(x);
    if (x === false) {
      setTimeout(() => {
        closePopUp();
      }, 300);
    }
  }
  const [checked, setChecked] = useState(false);
  const [name, setName] = useState(flows.find((f) => f.id === tabId).name);
  const [description, setDescription] = useState(
    flows.find((f) => f.id === tabId).description
  );

  const handleClose = () => {
    if (name === '') return setErrorData({
      title: t('code.keyInformationMissing'),
      list: [
        t('code.skillNameMissing')
      ],
    });
    if (checked)
      downloadFlow(
        flows.find((f) => f.id === tabId),
        name,
        description
      );
    else
      downloadFlow(
        removeApiKeys(flows.find((f) => f.id === tabId)),
        name,
        description
      );

    closePopUp();
  }
  return (
    <Dialog open={true} onOpenChange={setModalOpen}>
      <DialogTrigger asChild></DialogTrigger>
      <DialogContent className="h-[420px] lg:max-w-[600px] ">
        <DialogHeader>
          <DialogTitle className="flex items-center">
            <span className="pr-2">{t('code.export')}</span>
            <Download
              strokeWidth={1.5}
              className="h-6 w-6 pl-1 text-foreground"
              aria-hidden="true"
            />
          </DialogTitle>
          <DialogDescription>{t('code.exportToJSON')}</DialogDescription>
        </DialogHeader>

        <EditFlowSettings
          name={name}
          description={description}
          flows={flows}
          tabId={tabId}
          setName={setName}
          setDescription={setDescription}
          updateFlow={updateFlow}
        />
        <div className="flex items-center space-x-2">
          <Checkbox
            id="terms"
            onCheckedChange={(event: boolean) => {
              setChecked(event);
            }}
          />
          <label htmlFor="terms" className="export-modal-save-api text-sm">{t('code.useOwnAPIKeys')}</label>
        </div>

        <DialogFooter>
          <Button
            onClick={handleClose}
            type="submit"
          >
            {t('code.exportSkill')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

