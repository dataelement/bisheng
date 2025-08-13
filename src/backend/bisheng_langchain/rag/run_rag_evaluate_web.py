import os
import gradio as gr
import pandas as pd
from pathlib import Path
from gradio import components
from bisheng_langchain.rag.scoring.ragas_score import RagScore


save_folder = '/home/public/rag_benchmark_v1.0/rag_score_demo'
if not os.path.exists(save_folder):
    os.makedirs(save_folder)


def rag_evaluate(excel_file, metric='answer_recall_bisheng', batch_size=5):
    excel_path = excel_file.name
    df = pd.read_excel(excel_path)
    if '问题类型' not in df.columns:
        df['问题类型'] = len(df['问题'].tolist()) * ['QA']
    df.to_excel(excel_path, index=False)
    params = {
        'excel_path': excel_path,
        'save_path': save_folder,
        'question_column': '问题',
        'query_type_column': '问题类型',
        'gt_column': '人工标注',
        'answer_column': '模型回答',
        'metrics': [metric],
        'batch_size': int(batch_size),
    }
    rag_score = RagScore(**params)
    rag_score.score()

    output_path = Path(save_folder) / f"{Path(excel_path).stem}_score.xlsx"
    return str(output_path)


if __name__ == '__main__':
     title = """毕昇QA问答自动评估系统"""
     with gr.Blocks() as demo:
        gr.Markdown(title)
        
        with gr.Row():
            with gr.Column(scale=2):
                with gr.Row():
                    eval_intput_file = gr.components.File(label='FlowFile')
                    with gr.Column():
                        metric_options = ["answer_recall_bisheng", "answer_correctness_bisheng"]
                        metric = gr.components.Dropdown(label="评估方法", choices=metric_options, default=metric_options[0], interactive=True)
                        # metric = gr.Textbox(label='评估方法', value='answer_recall_bisheng', interactive=True, lines=2)
                        batch_size = gr.Textbox(label='批评估大小', value=5, interactive=True, lines=2)
                btn0 = gr.Button('Run Evaluation')
            eval_out_file = gr.components.File(label='FlowFile')

        btn0.click(fn=rag_evaluate, inputs=[eval_intput_file, metric, batch_size], outputs=[eval_out_file])
        demo.queue().launch(share=False, inbrowser=True, server_name="0.0.0.0", server_port=8218)