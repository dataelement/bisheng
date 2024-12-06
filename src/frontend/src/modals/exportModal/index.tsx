import { Checkbox } from "@/components/bs-ui/checkBox";
import { Download } from "lucide-react";
import { useContext, useState } from "react";
import { useTranslation } from "react-i18next";
import EditFlowSettings from "../../components/EditFlowSettingsComponent";
import { Button } from "../../components/bs-ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "../../components/bs-ui/dialog";
import { alertContext } from "../../contexts/alertContext";
import { PopUpContext } from "../../contexts/popUpContext";
import { TabsContext } from "../../contexts/tabsContext";
import { removeApiKeys } from "../../utils";

export default function ExportModal() {
  const { t } = useTranslation()

  const { closePopUp } = useContext(PopUpContext);

  const { setErrorData } = useContext(alertContext);
  const { flow, downloadFlow } = useContext(TabsContext);

  function setModalOpen(x: boolean) {
    if (x === false) {
      setTimeout(() => {
        closePopUp();
      }, 300);
    }
  }
  const [checked, setChecked] = useState(false);
  const [name, setName] = useState(flow.name);
  const [description, setDescription] = useState(flow.description);

  const handleClose = () => {
    if (name === '') return setErrorData({
      title: t('code.keyInformationMissing'),
      list: [
        t('code.skillNameMissing')
      ],
    });
    if (checked)
      downloadFlow(
        flow,
        name,
        description
      );
    else
      downloadFlow(
        removeApiKeys(flow),
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
          setName={setName}
          setDescription={setDescription}
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

