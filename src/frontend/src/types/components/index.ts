import { ReactElement, ReactNode } from "react";
import { APIClassType } from "../api";
import { NodeDataType } from "../flow/index";
import { typesContextType } from "../typesContext";
export type InputComponentType = {
  value: string;
  disabled?: boolean;
  onChange: (value: string) => void;
  password: boolean;
  disableCopyPaste?: boolean;
  editNode?: boolean;
  maxLength?: number;
  onChangePass?: (value: boolean | boolean) => void;
  showPass?: boolean;
};
export type ToggleComponentType = {
  enabled: boolean;
  setEnabled: (state: boolean) => void;
  disabled: boolean;
  size: "small" | "medium" | "large";
};
export type DropDownComponentType = {
  value: string;
  options: string[];
  onSelect: (value: string) => void;
  editNode?: boolean;
  apiModal?: boolean;
  numberOfOptions?: number;
};
export type ParameterComponentType = {
  data: NodeDataType;
  title: string;
  id: string;
  color: string;
  left: boolean;
  type: string;
  required?: boolean;
  name?: string;
  tooltipTitle: string;
  dataContext?: typesContextType;
  optionalHandle?: Array<String>;
  info?: string;
  onChange?: () => void;
};
export type InputListComponentType = {
  value: string[];
  onChange: (value: string[]) => void;
  disabled: boolean;
  editNode?: boolean;
  onAddInput?: (value?: string[]) => void;
};

export type KeyPairListComponentType = {
  value: any;
  onChange: (value: Object[]) => void;
  disabled: boolean;
  editNode?: boolean;
  duplicateKey?: boolean;
  advanced?: boolean | null;
  dataValue?: any;
};

export type DictComponentType = {
  value: any;
  onChange: (value) => void;
  disabled: boolean;
  editNode?: boolean;
};

export type TextAreaComponentType = {
  id?: number | '';
  field_name?: string;
  nodeClass?: APIClassType;
  setNodeClass?: (value: APIClassType) => void;
  disabled: boolean;
  onChange: (value: string[] | string) => void;
  value: string;
  editNode?: boolean;
};

export type CodeAreaComponentType = {
  disabled: boolean;
  onChange: (value: string[] | string) => void;
  value: string;
  editNode?: boolean;
  nodeClass: APIClassType;
  setNodeClass: (value: APIClassType) => void;
};

export type FileComponentType = {
  disabled: boolean;
  onChange: (value: string[] | string) => void;
  value: string;
  suffixes: Array<string>;
  fileTypes: Array<string>;
  onFileChange: (value: string) => void;
  editNode?: boolean;
  isSSO?: boolean;
  placeholder?: string;
};

export type DisclosureComponentType = {
  children: ReactNode;
  openDisc: boolean;
  button: {
    title: string;
    Icon: any;
    buttons?: {
      Icon: ReactElement;
      title: string;
      onClick: (event?: React.MouseEvent) => void;
    }[];
  };
};
export type FloatComponentType = {
  value: string;
  disabled?: boolean;
  disableCopyPaste?: boolean;
  onChange: (value: string) => void;
  editNode?: boolean;
};

export type TooltipComponentType = {
  children: ReactElement;
  title: string | ReactElement;
  placement?:
  | "bottom-end"
  | "bottom-start"
  | "bottom"
  | "left-end"
  | "left-start"
  | "left"
  | "right-end"
  | "right-start"
  | "right"
  | "top-end"
  | "top-start"
  | "top";
};

export type ProgressBarType = {
  children?: ReactElement;
  value?: number;
  max?: number;
};

export type RadialProgressType = {
  value?: number;
  color?: string;
};

export type AccordionComponentType = {
  children?: ReactElement;
  open?: string[];
  trigger?: string;
};
export type Side = "top" | "right" | "bottom" | "left";

export type ShadTooltipProps = {
  delayDuration?: number;
  side?: Side;
  content: ReactNode;
  children: ReactNode;
  style?: string;
};
export type ShadToolTipType = {
  content?: ReactNode;
  side?: "top" | "right" | "bottom" | "left";
  asChild?: boolean;
  children?: ReactElement;
  delayDuration?: number;
  styleClasses?: string;
};

export type TextHighlightType = {
  value?: string;
  side?: "top" | "right" | "bottom" | "left";
  asChild?: boolean;
  children?: ReactElement;
  delayDuration?: number;
};

export interface IVarHighlightType {
  name: string;
}

export type IconComponentProps = {
  name: string;
  className?: string;
  iconColor?: string;
  onClick?: () => void;
};

export type modalHeaderType = {
  children: ReactNode;
  description: string | null;
};