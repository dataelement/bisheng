export enum EvaluationType {
    flow = 'flow',
    assistant = 'assistant'
}

export const EvaluationTypeLabelMap = {
    [EvaluationType.flow]: {
        label: '技能'
    },
    [EvaluationType.assistant]: {
        label: '助手'
    }
}
  
export enum EvaluationScore {
    answer_f1 = 'answer_f1',
    answer_precision = 'answer_precision',
    answer_recall = 'answer_recall',
}

export const EvaluationScoreLabelMap = {
    [EvaluationScore.answer_f1]: {
        label: 'F1'
    },
    [EvaluationScore.answer_precision]: {
        label: '准确率'
    },
    [EvaluationScore.answer_recall]: {
        label: '召回率'
    }
}
  
export const EvaluationStatusLabelMap = {
    [1]: {
        label: '进行中'
    },
    [2]: {
        label: '失败'
    },
    [3]: {
        label: '成功'
    }
}