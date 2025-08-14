import json
import os
import numpy as np
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained('/home/public/llm/bge-reranker-large')
model = AutoModelForSequenceClassification.from_pretrained('/home/public/llm/bge-reranker-large').to('cuda:2')
model.eval()


def min_edit_distance(a, b):
    dp = [[0 for i in range(len(b) + 1)] for j in range(len(a) + 1)]
    for i in range(len(a) + 1):
        dp[i][0] = i
    for j in range(len(b) + 1):
        dp[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + 1)
    return dp[-1][-1]


def is_matched(text0, text1, thrd=10):
    text0.replace(" ", "").replace("\n", "")
    text1.replace(" ", "").replace("\n", "")
    dist = min_edit_distance(text0, text1)
    if dist < thrd:
        return True
    return False


def match_score(chunk, query):
    """
    rerank模型计算query和chunk的相似度
    """
    pairs = [[query, chunk]]

    with torch.no_grad():
        inputs = tokenizer(pairs, padding=True, truncation=True, return_tensors='pt', max_length=512).to('cuda:2')
        scores = model(**inputs, return_dict=True).logits.view(-1, ).float()
        scores = torch.sigmoid(scores) 
        scores = scores.cpu().numpy()
        
    return scores[0]


def sort_filter_all_chunks_method1(d, th=0.0):
    """
    rerank模型对所有chunk进行排序
    """
    # answer关键词已提取好
    query = d['question']
    all_chunks = d['all_chunks']

    chunk_match_score = []
    for index, chunk in enumerate(all_chunks):
        chunk_text = chunk['text']
        chunk_match_score.append(match_score(chunk_text, query))

    sorted_res = sorted(enumerate(chunk_match_score), key=lambda x: -x[1])
    print('-----------')
    print(sorted_res)
    remain_chunks = [all_chunks[elem[0]] for elem in sorted_res if elem[1] >= th]
    if not remain_chunks:
        remain_chunks = [all_chunks[sorted_res[0][0]]]

    # for index, chunk in enumerate(remain_chunks):
    #     print('query:', query)
    #     print('chunk_text:', chunk['text'])
    #     print('socre:', sorted_res[index][1])
    #     print('***********')

    d['all_chunks'] = remain_chunks


def calc_precision_recall(d):
    """
    计算分数
    """
    d_ves = d["all_chunks"][:10]
    d_es = d["all_chunks"][10:]
    all_chunks = []
    for i in range(len(d_es)):
        all_chunks.append(d_es[i])
        all_chunks.append(d_ves[i])
    all_chunks.extend(d_ves[i+1:])
    d["all_chunks"] = all_chunks
    
    sort_filter_all_chunks_method1(d)
    NCHUNK = len(d["chunks"])
    NCHUNK_ALL = len(d["all_chunks"])
    print('chunks:', NCHUNK, 'all_chunks:', NCHUNK_ALL)

    scores = np.zeros((NCHUNK, NCHUNK_ALL))
    for j in range(NCHUNK):
        for i in range(NCHUNK):
            if d["chunks"][j]["text"] == d["all_chunks"][i]['text']:
                scores[j][i] = 1
            elif abs(len(d["chunks"][j]["text"]) - len(d["all_chunks"][i]['text'])) > 10:
                scores[j][i] = 0
            elif is_matched(d["chunks"][j]["text"], d["all_chunks"][i]['text']):
                scores[j][i] = 1

    N_gt = NCHUNK
    N_all = NCHUNK_ALL
    if NCHUNK != 0:
        N_right = sum(scores.max(axis=1))
    else:
        N_right = 0
    recall = 0 if N_gt == 0 else N_right / N_gt
    return recall, N_gt, N_right, N_all


with open('zhaogushu_retriever_gt_convert_key.json', 'r') as f:
    retriever_gt_list = json.load(f)
mFieldRecall = 0
total_N_gt, total_N_right, total_N_all = 0, 0, 0
D_SCORES = {}
nquestion = 0
for d in retriever_gt_list:
    recall, N_gt, N_right, N_all = calc_precision_recall(d)
    mFieldRecall += recall
    D_SCORES[d["question"]] = {'recall': recall}
    total_N_gt += N_gt
    total_N_right += N_right
    total_N_all += N_all
    nquestion += 1

mFieldRecall = 0 if nquestion == 0 else mFieldRecall / nquestion
mMethodRecall = total_N_right / total_N_gt

print(f'mFieldRecall: {mFieldRecall * 100:.2f} %')
print(f'mMethodRecall: {mMethodRecall * 100:.2f} %')
print(f'total_N_right: {total_N_right}, total_N_gt: {total_N_gt}, total_N_all: {total_N_all}' )
print(f'nquestion: {nquestion}, mean_N_right: {total_N_right / nquestion}, mean_N_gt: {total_N_gt / nquestion}, mean_N_all: {total_N_all / nquestion}')