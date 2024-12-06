import json
import os
from queue import Queue
from typing import Dict

from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.graph.workflow import Workflow


def main(workflow_data: Dict = None):
    base_callback = BaseCallback()
    input_queue = Queue()

    workflow = Workflow(workflow_id='zgq_1', user_id='1', workflow_data=workflow_data, max_steps=10, timeout=1,
                        callback=base_callback, input_queue=input_queue)
    print(workflow.run())


if __name__ == '__main__':
    print(os.getcwd())
    with open('./workflow_data.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    main(data)
