import os
import sys
sys.path.append(os.path.dirname(os.getcwd()))
from langchain.chains import TransformChain

def transform_query_analyze_result(inputs: dict) -> dict:
    query = inputs.get("query")
    func = inputs.get("func") 
    
    if func is not None and callable(func):  # 检查func是否存在且为可调用对象
        result = func(query)
    else:
        result = None  # 处理func不存在或不可调用的情况
    return {"query_analyze_result": result}

transform_query_analyze_result_chain = TransformChain(
    input_variables=["query", "func"], output_variables=["query_analyze_result"], transform=transform_query_analyze_result
)