import os
import random
import json
import copy
import pandas as pd
from loguru import logger
from tqdm import tqdm
from langchain.document_loaders import PyPDFLoader
from langchain_core.prompts import PromptTemplate
from bisheng_langchain.document_loaders import ElemUnstructuredLoader
from bisheng_ragas.trainset import TrainsetGenerator


prompt_template = """Use the following pieces of context to answer the question at the end. If you don't know the answer, just say that you don't know, don't try to make up an answer.

{context}

Question: {question}
Helpful Answer:"""
PROMPT = PromptTemplate(
    template=prompt_template, input_variables=["context", "question"]
)


class RagQAGenerator(object):

    def __init__(self, 
                 corpus_folder,
                 qa_gen_folder,
                 unstructured_api_url="https://bisheng.dataelem.com/api/v1/etl4llm/predict",
                 model_name="gpt-4-0125-preview"):
        self.unstructured_api_url = unstructured_api_url
        self.corpus_folder = corpus_folder
        self.qa_gen_folder = qa_gen_folder
        self.model_name = model_name
        if not os.path.exists(self.qa_gen_folder):
            os.makedirs(self.qa_gen_folder)
    
    def generate(self):
        for file_name in tqdm(os.listdir(self.corpus_folder)):
            file_path = os.path.join(self.corpus_folder, file_name)
            logger.info(f'{file_name} generate qa start ...')
            # only consider pdf file
            if file_name.endswith('.pdf'):
                self.generate_qa_each_file(file_path)
            else:
                continue

    def generate_qa_each_file(self, file_path, train_size=100):
        file_name = os.path.basename(file_path)
        loader = ElemUnstructuredLoader(file_name=file_name,
                                        file_path=file_path,
                                        unstructured_api_url=self.unstructured_api_url)
        documents = loader.load()
        for doc in documents:
            doc.metadata = dict()
        logger.info(f'documents: {len(documents)}')

        trainsetgenerator = TrainsetGenerator.from_default(
            openai_generator_llm=self.model_name,
            openai_filter_llm=self.model_name)
        trainset = trainsetgenerator.generate(documents, train_size=train_size)

        save_path = os.path.join(self.qa_gen_folder, os.path.splitext(file_name)[0] + '_qa_gen.xlsx')
        df = trainset.to_pandas()
        df.to_excel(save_path, index=False)
        return save_path
    
    def statistic_qa(self):
        total_qa_num = 0
        all_qa_info = dict()
        for file_name in os.listdir(self.qa_gen_folder):
            file_path = os.path.join(self.qa_gen_folder, file_name)
            if file_name.endswith('.xlsx'):
                df = pd.read_excel(file_path)
                qa_info = df.to_dict('records')
                logger.info(f'{file_name} qa num: {len(qa_info)}')
                total_qa_num += len(qa_info)
                all_qa_info[file_name] = qa_info
        logger.info(f'total_file_num: {len(list(all_qa_info.keys()))}, total_qa_num: {total_qa_num}')
        return all_qa_info

    def format_qa_for_sft(self, min_context_num=3, max_context_num=7):
        random.seed(123)
        all_qa_info = self.statistic_qa()
        train_samples = []
        test_samples = []
        for file_name in all_qa_info:
            # each file qa
            qa_info = all_qa_info[file_name]
            if len(qa_info) == 0:
                continue
            contexts = []
            for qa in qa_info:
                ground_truth_context = str(eval(qa['ground_truth_context'])[0])
                contexts.append(ground_truth_context)
            
            random.shuffle(qa_info)
            for i, qa in enumerate(qa_info):
                question = qa['question']
                ground_truth_context = str(eval(qa['ground_truth_context'])[0])
                ground_truth = str(eval(qa['ground_truth'])[0])
                
                # 加入其他干扰context
                random_number = random.randint(
                    min(min_context_num, len(contexts)), 
                    min(max_context_num, len(contexts))
                )
                random_context = random.sample(contexts, random_number)
                if ground_truth_context in random_context:
                    random_context.remove(ground_truth_context)
                # 将当前context随机插入到其他context中
                insert_position = random.randint(0, len(random_context))
                random_context.insert(insert_position, ground_truth_context)

                random_context = '\n\n'.join(random_context)
                prompt = PROMPT.format(context=random_context, question=question)
                each_sample = {
                    'instruction': '', 
                    'input': prompt, 
                    'output': ground_truth,
                    'history': []
                }
                if i < 0.9 * len(qa_info):
                    train_samples.append(each_sample)
                else:
                    test_samples.append(each_sample)
             
        logger.info(f'train_samples: {len(train_samples)} test_samples: {len(test_samples)}')
        save_folder = os.path.dirname(self.qa_gen_folder)
        with open(os.path.join(save_folder, f'train_samples_ganrao_chunk{max_context_num+1}.json'), 'w') as f:
            json.dump(train_samples, f, indent=2, ensure_ascii=False)
        with open(os.path.join(save_folder, f'test_samples_ganrao_chunk{max_context_num+1}.json'), 'w') as f:
            json.dump(test_samples, f, indent=2, ensure_ascii=False)


if __name__ == '__main__':
    corpus_folder = '/home/public/rag_benchmark_v1.0/rag_benchmark_processed'
    qa_gen_folder = '/home/public/rag_benchmark_v1.0/rag_qa_gen_filter'
    generator = RagQAGenerator(corpus_folder=corpus_folder, qa_gen_folder=qa_gen_folder)
    # generator.generate()
    # generator.statistic_qa()
    generator.format_qa_for_sft(min_context_num=5, max_context_num=11)
