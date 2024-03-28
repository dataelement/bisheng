import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer


class CustomReranker:

    def __init__(self, model_path, device_id='cuda:0', threshold=0.0):
        self.device_id = device_id
        self.threshold = threshold
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        self.rank_model = AutoModelForSequenceClassification.from_pretrained(model_path).to(device_id)
        self.rank_model.eval()

    def match_score(self, chunk, query):
        """
        rerank模型计算query和chunk的相似度
        """
        pairs = [[query, chunk]]

        with torch.no_grad():
            inputs = self.tokenizer(pairs, padding=True, truncation=True, return_tensors='pt', max_length=512).to(self.device_id)
            scores = self.rank_model(**inputs, return_dict=True).logits.view(-1, ).float()
            scores = torch.sigmoid(scores) 
            scores = scores.cpu().numpy()
            
        return scores[0]

    def sort_and_filter(self, query, all_chunks):
        """
        rerank模型对所有chunk进行排序
        """
        chunk_match_score = []
        for index, chunk in enumerate(all_chunks):
            chunk_text = chunk.page_content
            chunk_match_score.append(self.match_score(chunk_text, query))

        sorted_res = sorted(enumerate(chunk_match_score), key=lambda x: -x[1])
        remain_chunks = [all_chunks[elem[0]] for elem in sorted_res if elem[1] >= self.threshold]
        if not remain_chunks:
            remain_chunks = [all_chunks[sorted_res[0][0]]]

        # for index, chunk in enumerate(remain_chunks):
        #     print('query:', query)
        #     print('chunk_text:', chunk.page_content)
        #     print('socre:', sorted_res[index][1])
        #     print('***********')

        return remain_chunks