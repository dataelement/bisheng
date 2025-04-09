export enum EvaluationType {
  flow = "flow",
  assistant = "assistant",
}

export const EvaluationTypeLabelMap = {
  [EvaluationType.flow]: {
    label: "build.skill",
  },
  [EvaluationType.assistant]: {
    label: "build.assistant",
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
    label: "准确率",
  },
  [EvaluationScore.answer_recall]: {
    label: "召回率",
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
