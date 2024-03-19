import os
import pandas as pd

excel_folder = '/home/public/rag_benchmark_v1.0/rag_qa_gen_filter_origin'
save_folder = '/home/public/rag_benchmark_v1.0/rag_qa_gen_filter'
excel_files = os.listdir(excel_folder)

total_correct = 0
total_num = 0
for excel_file in excel_files:
    # if excel_file != '96_MA_IFC300_cn_100909_4000069803_R04_qa_gen.xlsx':
    #     continue
    if not excel_file.endswith('.xlsx'):
        continue
    excel_path = os.path.join(excel_folder, excel_file)
    df = pd.read_excel(excel_path)
    qa_info = df.to_dict('records')
    correct_qa = []
    for qa in qa_info:
        if 'Unnamed: 1' in qa:
            qes_key = 'Unnamed: 1'
        elif '问题类型' in qa:
            qes_key = '问题类型'
        else:
            raise ValueError('key not found')
        
        if 'Unnamed: 4' in qa:
            ans_key = 'Unnamed: 4'
        elif '答案类型' in qa:
            ans_key = '答案类型'
        else:
            raise ValueError('key not found')

        valid_qa = dict()
        for key in qa:
            valid_qa[key.strip()] = qa[key]

        total_num += 1
        if isinstance(qa[qes_key], str) and qa[qes_key].strip() == '正确' and isinstance(qa[ans_key], str) and qa[ans_key].strip() == '正确':
            total_correct += 1
            correct_qa.append(valid_qa)
        else:
            print(qa[qes_key], qa[ans_key])
            print(excel_file)

    df = pd.DataFrame(correct_qa)
    df.to_excel(os.path.join(save_folder, excel_file), index=False)

print('total_correct:', total_correct)
print('total_num:', total_num)

