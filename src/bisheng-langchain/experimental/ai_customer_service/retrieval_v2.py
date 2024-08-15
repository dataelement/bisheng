import hashlib
import json
import math
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import List, Optional

import pandas as pd
import requests
import torch
from loguru import logger
from sentence_transformers import SentenceTransformer, util
from tqdm import tqdm
from transformers import (
    AutoModelForCausalLM,
    AutoModelForSequenceClassification,
    AutoTokenizer,
)


def md5(string):
    md5 = hashlib.md5()
    md5.update(string.encode("utf-8"))
    return md5.hexdigest()


def load_reranker(model_name_or_path: str, device: str = 'cuda:2'):
    tokenizer = AutoTokenizer.from_pretrained(model_name_or_path)
    model = AutoModelForSequenceClassification.from_pretrained(model_name_or_path).to(device)
    model.eval()
    return model, tokenizer


def load_llm_reranker(model_name_or_path: str, device: str = 'cuda:2'):
    tokenizer = AutoTokenizer.from_pretrained(model_name_or_path, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(model_name_or_path, trust_remote_code=True).to(device)
    yes_loc = tokenizer('Yes', add_special_tokens=False)['input_ids'][0]
    model.eval()
    return model, tokenizer, yes_loc


def do_llm_rerank(
    model: AutoModelForSequenceClassification,
    tokenizer: AutoTokenizer,
    pairs: List[List[str]],
    yes_loc: int,
    device: str = 'cuda:2',
):
    def get_inputs(pairs, tokenizer, prompt=None, max_length=1024):
        if prompt is None:
            prompt = "给定问题 A 和问题 B，通过预测 'Yes'或 'No' 来确定问题 A 和问题 B 所表达的意思是否相同。"
        sep = "\n"
        prompt_inputs = tokenizer(prompt, return_tensors=None, add_special_tokens=False)['input_ids']
        sep_inputs = tokenizer(sep, return_tensors=None, add_special_tokens=False)['input_ids']
        inputs = []
        for query, passage in pairs:
            query_inputs = tokenizer(
                f'问题 A: {query}',
                return_tensors=None,
                add_special_tokens=False,
                max_length=max_length * 3 // 4,
                truncation=True,
            )
            passage_inputs = tokenizer(
                f'问题 B: {passage}',
                return_tensors=None,
                add_special_tokens=False,
                max_length=max_length,
                truncation=True,
            )
            item = tokenizer.prepare_for_model(
                [tokenizer.bos_token_id] + query_inputs['input_ids'],
                sep_inputs + passage_inputs['input_ids'],
                truncation='only_second',
                max_length=max_length,
                padding=False,
                return_attention_mask=False,
                return_token_type_ids=False,
                add_special_tokens=False,
            )
            item['input_ids'] = item['input_ids'] + sep_inputs + prompt_inputs
            item['attention_mask'] = [1] * len(item['input_ids'])
            inputs.append(item)
        return tokenizer.pad(
            inputs,
            padding=True,
            max_length=max_length + len(sep_inputs) + len(prompt_inputs),
            pad_to_multiple_of=8,
            return_tensors='pt',
        )

    with torch.no_grad():
        inputs = get_inputs(pairs, tokenizer).to(device)
        scores = (
            model(**inputs, return_dict=True)
            .logits[:, -1, yes_loc]
            .view(
                -1,
            )
            .float()
        )
        scores, indices = torch.topk(scores, k=1)
        return scores, indices


def do_rerank(
    model: AutoModelForSequenceClassification,
    tokenizer: AutoTokenizer,
    pairs: List[List[str]],
    device: str = 'cuda:2',
) -> torch.Tensor:
    with torch.no_grad():
        inputs = tokenizer(
            pairs,
            padding=True,
            truncation=True,
            return_tensors='pt',
            max_length=512,
        ).to(device)
        scores = (
            model(**inputs, return_dict=True)
            .logits.view(
                -1,
            )
            .float()
        )
        scores, indices = torch.topk(scores, k=1)
    return scores, indices


class LlmBasedLayerwiseReranker:
    def __init__(self, model_path, device) -> None:
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        self.model = AutoModelForCausalLM.from_pretrained(model_path, trust_remote_code=True)
        self.model = self.model.to(device)
        self.model.eval()
        self.prompt = "给定问题 A 和问题 B，通过输出 'Yes' 或 'No'来确定问题 A 和问题 B 所指向的问题是否相同。"

    def get_inputs(self, pairs, max_length=1024):
        if self.prompt is None:
            self.prompt = "Given a query A and a passage B, determine whether the passage contains an answer to the query by providing a prediction of either 'Yes' or 'No'."
        sep = "\n"
        prompt_inputs = self.tokenizer(self.prompt, return_tensors=None, add_special_tokens=False)['input_ids']
        sep_inputs = self.tokenizer(sep, return_tensors=None, add_special_tokens=False)['input_ids']
        inputs = []
        for query, passage in pairs:
            query_inputs = self.tokenizer(
                f'问题 A: {query}',
                return_tensors=None,
                add_special_tokens=False,
                max_length=max_length * 3 // 4,
                truncation=True,
            )
            passage_inputs = self.tokenizer(
                f'问题 B: {passage}',
                return_tensors=None,
                add_special_tokens=False,
                max_length=max_length,
                truncation=True,
            )
            item = self.tokenizer.prepare_for_model(
                [self.tokenizer.bos_token_id] + query_inputs['input_ids'],
                sep_inputs + passage_inputs['input_ids'],
                truncation='only_second',
                max_length=max_length,
                padding=False,
                return_attention_mask=False,
                return_token_type_ids=False,
                add_special_tokens=False,
            )
            item['input_ids'] = item['input_ids'] + sep_inputs + prompt_inputs
            item['attention_mask'] = [1] * len(item['input_ids'])
            inputs.append(item)
        return self.tokenizer.pad(
            inputs,
            padding=True,
            max_length=max_length + len(sep_inputs) + len(prompt_inputs),
            pad_to_multiple_of=8,  # 2^n
            return_tensors='pt',
        )

    def rerank(self, pairs, k=1):
        with torch.no_grad():
            inputs = self.get_inputs(pairs).to(
                self.model.device
            )  # "<unk><s> 问题 A: 自动退票TRFD Z报错：PLEASE CHECK REFUND NUMBER，该怎么处理？ \n 问题 B: 出现自动退票TRFD:Z提示“PLEASE CHECK REFUND NUMBER”我该如何处理？ \n 给定问题 A 和问题 B，通过输出 'Yes' 或 'No'来确定问题 A 和问题 B 所指向的问题是否相同。"
            all_scores = self.model(**inputs, return_dict=True, cutoff_layers=[28])
            # print(all_scores.logits[0].shape)
            all_scores = [scores[:, -1].view(-1).float() for scores in all_scores[0]]
            score, ind = torch.topk(all_scores[0], k=k)
            return score, ind


@dataclass
class VectorSearch:
    embedding_model: SentenceTransformer
    store_name: str
    docs: List[str]
    read_cache: bool = True
    vector_cache_path: str = './cache/vector_cache'
    drop_old_cache: bool = False
    instruction: str = "为这个句子生成表示以用于检索类似的问题："

    def __post_init__(self):
        self.cache_path = Path(self.vector_cache_path) / f"{md5(self.store_name)}.pt"
        if self.drop_old_cache and self.cache_path.exists():
            self.cache_path.unlink()
        if not self.cache_path.parent.exists():
            self.cache_path.parent.mkdir(exist_ok=True, parents=True)
        self.store = self.build_vector_store(self.docs)

    def search(self, query: str, add_instruction=False, topk=3, threshold=0.9):
        if add_instruction:
            query = self.instruction + query
        query_embedding = self.embedding_model.encode(query, convert_to_tensor=True)
        similarity_scores = util.pytorch_cos_sim(query_embedding, self.store)[0]
        scores, indices = torch.topk(similarity_scores, k=topk)
        _indices = indices[scores > threshold]
        return [self.docs[i] for i in _indices]

    def build_vector_store(self, docs):
        if self.read_cache:
            if self.cache_path.exists():
                try:
                    store = torch.load(self.cache_path, map_location=torch.device('cuda'))
                except Exception as e:
                    logger.error(f"load cache {self.store_name} failed: {e}")
                    logger.error("尝试删除旧缓存文件再试试")
            else:
                start = time()
                store = self.embedding_model.encode(docs, convert_to_tensor=True)
                torch.save(store, self.cache_path)
                print(f"build vectors {self.store_name} time cost: {time() - start}s")
        else:
            store = self.embedding_model.encode(docs, convert_to_tensor=True)

        return store


def eval_retrieval_v3():
    input_data = '/public/youjiachen/workspace/移动九天/data/第二批数据.xlsx'
    knowledge_data = pd.read_csv('./data/第二批train.csv')['Question'].tolist()

    rerank_llm_model_path = '/public/youjiachen/models/buaadreamer/bge-reranker-v2-minicpm-layerwise'
    embedding_model_path = '/public/youjiachen/models/AI-ModelScope/bge-large-zh-v1___5'

    data = pd.read_excel(input_data).dropna(subset=['query', 'labels'])
    vector_search = VectorSearch(
        embedding_model=SentenceTransformer(embedding_model_path).to('cuda:1'),
        store_name='第二批',
        docs=knowledge_data,
        read_cache=True,
        drop_old_cache=True,
    )

    # _result_df = data.drop(
    #     columns=[
    #         'vector predict title',
    #         'keyword predict',
    #         'keyword predict title',
    #         'keyword score',
    #         'score',
    #     ]
    # )
    _result_df = data
    # reranker, tokenizer = load_reranker(rerank_model_path)
    # reranker, tokenizer, yes_loc = load_llm_reranker(rerank_llm_model_path)
    reranker = LlmBasedLayerwiseReranker(rerank_llm_model_path, 'cuda:2')
    for idx, row in tqdm(data.iterrows(), total=len(data)):
        query = row['query']
        label = eval(row['labels'])

        # result = vector_search.search(query, add_instruction=True, topk=10, threshold=0.7)
        result = vector_search.search(query, add_instruction=False, topk=10, threshold=0.7)
        if not len(result):
            if not len(label):
                _result_df.loc[idx, 'vector score'] = 1
            else:
                _result_df.loc[idx, 'vector score'] = 0
            continue

        rerank_score, rerank_inds = reranker.rerank([[query, r] for r in result])
        if rerank_inds is not None and {result[rerank_inds]} & set(label):
            _result_df.loc[idx, 'vector predict'] = result[rerank_inds]
            _result_df.loc[idx, 'vector score'] = 1
        else:
            _result_df.loc[idx, 'vector predict'] = result[rerank_inds]
            _result_df.loc[idx, 'vector score'] = 0
    # _result_df.to_excel('./retrieval_v4.xlsx', index=False)
    logger.info(f"平均准确率为{_result_df['vector score'].mean()}")


if __name__ == '__main__':
    eval_retrieval_v3()
    pass
