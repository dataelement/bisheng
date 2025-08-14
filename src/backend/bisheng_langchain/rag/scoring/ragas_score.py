import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd
from datasets import Dataset
from loguru import logger
from bisheng_ragas import evaluate
from bisheng_ragas.metrics import AnswerCorrectness, AnswerCorrectnessBisheng, AnswerRecallBisheng


@dataclass
class RagScore:
    excel_path: str
    save_path: str
    question_column: str
    gt_column: str
    answer_column: str
    metrics: List[str]
    contexts_column: Optional[str] = None
    query_type_column: Optional[str] = None
    gt_split_column: Optional[str] = None
    batch_size: int = 5
    whether_gtsplit: bool = False

    def _validate_metrics(self):
        for metric in self.metrics:
            if not hasattr(self, f'ragas_{metric}'):
                raise Exception(f'"ragas_{metric}" 未实现!')

    def ragas_answer_correctness(self, dataset: Dataset) -> pd.DataFrame:
        # answer_correctness, 只考虑事实相似度
        weights = [1.0, 0.0]
        answer_correctness = AnswerCorrectness(weights=weights, batch_size=self.batch_size)
        result = evaluate(
            dataset=dataset,
            metrics=[
                answer_correctness,
            ],
        )
        self.score_map_keys = list(result.keys())
        df = result.to_pandas()
        return df

    def ragas_answer_correctness_bisheng(self, dataset: Dataset) -> pd.DataFrame:
        answer_correctness = AnswerCorrectnessBisheng(batch_size=self.batch_size)
        result = evaluate(
            dataset=dataset,
            metrics=[answer_correctness],
        )
        self.score_map_keys = list(result.keys())
        df = result.to_pandas()
        return df

    def ragas_answer_recall_bisheng(self, dataset: Dataset) -> pd.DataFrame:
        answer_recall =AnswerRecallBisheng(batch_size=self.batch_size, 
                                           whether_gtsplit=self.whether_gtsplit)
        result = evaluate(
            dataset=dataset,
            metrics=[answer_recall],
        )
        self.score_map_keys = list(result.keys())
        df = result.to_pandas()
        return df

    def _remove_source(self, pred: str) -> str:
        """去除【1†source】, only for openai assistant"""
        pattern = re.compile("【(\d+)†source】")
        match = re.findall(pattern, pred)
        for i in match:
            str_temp = f"【{i}†source】"
            pred = pred.replace(str_temp, '')
        return pred

    def score(self) -> Tuple[pd.DataFrame, Optional[pd.DataFrame]]:
        df = pd.read_excel(self.excel_path)
        ori_row_nums = df.shape[0]

        # 删除含有na的行
        columns_to_check = [
            self.question_column,
            self.gt_column,
            self.answer_column,
            self.contexts_column,
            self.query_type_column,
        ]
        # 是否有要点拆分列
        if self.gt_split_column:
            columns_to_check.append(self.gt_split_column)

        df.dropna(subset=[col for col in columns_to_check if col], inplace=True)
        df = df.reset_index()
        print(f'删除含有na的行 {ori_row_nums - df.shape[0]} 个!')
        print(f'总计 {df.shape[0]} 个问题')

        questions = df[self.question_column].tolist()
        answers = df[self.answer_column].tolist()
        # answers = df[self.answer_column].apply(self._remove_source).tolist() # for openai assistant
        ground_truths = df[self.gt_column].apply(lambda x: [x]).tolist()
        # todo: contexts可能是保存在json中的，这段代码可能需要修改
        contexts = (
            [['']] * len(questions)
            if not self.contexts_column
            else df[self.contexts_column].apply(lambda x: [x]).tolist()
        )
        # To dict
        if self.gt_split_column:
            gtsplit = df[self.gt_split_column].tolist()
            data: Dict[str, List[Any]] = {
                "question": questions,
                "answer": answers,
                "contexts": contexts,
                "ground_truths": ground_truths,
                'gt_split_point': gtsplit
            }
        else:
            data: Dict[str, List[Any]] = {
                "question": questions,
                "answer": answers,
                "contexts": contexts,
                "ground_truths": ground_truths,
            }
        # Convert dict to dataset
        dataset = Dataset.from_dict(data)

        self._validate_metrics()

        save_group_df = dict()
        for metric_name in self.metrics:
            ragas_result = getattr(self, f'ragas_{metric_name}')(dataset)
            if metric_name =='answer_recall_bisheng':
                if self.gt_split_column:
                    df[self.gt_split_column] = ragas_result["gt_split_point"]
                else:
                    df["gt_split_point"] = ragas_result["gt_split_point"]
                df["analyse"] = ragas_result["analyse"]

            score_map = dict().fromkeys(self.score_map_keys, ragas_result)
            for metric, scores in score_map.items():
                df[metric] = df.index.map({idx: rows[metric] for idx, rows in scores.iterrows()})

            if self.query_type_column and self.query_type_column in df.columns:
                grouped_df = df.groupby(self.query_type_column)
                grouped_df = grouped_df.agg({self.question_column: 'count', **{metric: 'mean' for metric in score_map}})
                grouped_df.rename(columns={self.question_column: '问题个数'}, inplace=True)
                
                total_question = grouped_df['问题个数'].sum()
                grouped_df.loc['总计', '问题个数'] = total_question
                for metric in score_map:
                    grouped_df.loc['总计', metric] = df[metric].sum() / total_question
                save_group_df[f'{metric_name}_group'] = grouped_df
                
                print(grouped_df.to_markdown())

        # save
        output_path = Path(self.save_path) / f"{Path(self.excel_path).stem}_score.xlsx"
        with pd.ExcelWriter(output_path) as writer:
            df.to_excel(writer, sheet_name='Sheet1', index=False)
            if len(save_group_df):
                for metric, grouped_df in save_group_df.items():
                    grouped_df.to_excel(writer, sheet_name=metric, index=True)
        print(f'保存到 {output_path} 成功!')


if __name__ == '__main__':
    params = {
        'excel_path': '/home/gulixin/workspace/llm/bisheng/src/bisheng-langchain/experimental/rag/data/test.xlsx',
        'save_path': '/home/gulixin/workspace/llm/bisheng/src/bisheng-langchain/experimental/rag/data',
        'question_column': '问题',
        'gt_column': 'GT',
        'answer_column': 'rag_answer',
        'query_type_column': '问题类型',
        # 'metrics': ['answer_correctness_bisheng'],
        'metrics': ['answer_recall_bisheng'],
        'batch_size': 10,
        'whether_gtsplit': False,
    }
    rag_score = RagScore(**params)
    rag_score.score()
