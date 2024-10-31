import { ReactNode } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { TooltipProvider } from "../components/bs-ui/tooltip";
import { SSEProvider } from "./SSEContext";
import { AlertProvider } from "./alertContext";
import { DarkProvider } from "./darkContext";
import { LocationProvider } from "./locationContext";
import PopUpProvider from "./popUpContext";
import { TabsProvider } from "./tabsContext";
import { TypesProvider } from "./typesContext";
import { UndoRedoProvider } from "./undoRedoContext";
import { UserProvider } from "./userContext";

export default function ContextWrapper({ children }: { children: ReactNode }) {
  //element to wrap all context
  return (
    <>
      <TooltipProvider>
        <ReactFlowProvider>
          <DarkProvider>
            <TypesProvider>
              <LocationProvider>
                <AlertProvider>
                  <SSEProvider>
                    <TabsProvider>
                      <UndoRedoProvider>
                        <UserProvider>
                          <PopUpProvider>{children}</PopUpProvider>
                        </UserProvider>
                      </UndoRedoProvider>
                    </TabsProvider>
                  </SSEProvider>
                </AlertProvider>
              </LocationProvider>
            </TypesProvider>
          </DarkProvider>
        </ReactFlowProvider>
      </TooltipProvider>
    </>
  );
}
