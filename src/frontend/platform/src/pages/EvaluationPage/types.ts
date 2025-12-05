export enum EvaluationType {
  flow = "flow",
   skill = "skill",  
  assistant = "assistant",
  workflow = "workflow"
}

export const EvaluationTypeLabelMap = {
  [EvaluationType.flow]: {
    label: "build.skill",
  },
  [EvaluationType.skill]: { label: "build.skill" },
  [EvaluationType.assistant]: {
    label: "build.assistant",
  },
   [EvaluationType.workflow]: {
    label: "build.workflow",
  },
};

export enum EvaluationScore {
  answer_f1 = "answer_f1",
  answer_precision = "answer_precision",
  answer_recall = "answer_recall",
}

export const EvaluationScoreLabelMap = {
  [EvaluationScore.answer_f1]: {
    label: "F1",
  },
  [EvaluationScore.answer_precision]: {
    label: "evaluation.precision",
  },
  [EvaluationScore.answer_recall]: {
    label: "evaluation.recall",
  },
};

export enum EvaluationStatusEnum {
  running = 1,
  failed = 2,
  success = 3,
}
export const EvaluationStatusLabelMap = {
  [EvaluationStatusEnum.running]: {
    label: "inProgress",
    variant: "secondary",
  },
  [EvaluationStatusEnum.failed]: {
    label: "failed",
    variant: "destructive",
  },
  [EvaluationStatusEnum.success]: {
    label: "success",
    variant: "default",
  },
};
