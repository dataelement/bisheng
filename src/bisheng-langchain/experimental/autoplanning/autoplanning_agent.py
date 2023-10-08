import os
import sys
import json
import copy
from collections import defaultdict
from time import sleep
from tqdm import trange
from planning_chain import Chains
from graph.graph import GraphGenerator
from prompts.task_definitions import TASK2COMPONENTS, COMPONENT_PARAMS


class AutoPlanning:

    def __init__(
        self,
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        model_name="gpt-4-0613",
        max_steps=10,
        openai_api_base="",
    ):
        assert len(
            openai_api_key.strip()
        ), "Either give openai_api_key as an argument or put it in the environment variable"
        self.model_name = model_name
        self.openai_api_key = openai_api_key
        self.max_steps = max_steps  # max iteration for refining the model purpose
        self.openai_api_base = openai_api_base
        Chains.setLlm(
            self.model_name, self.openai_api_key, openai_api_base=self.openai_api_base
        )

    def setModel(self, model_name):
        self.model_name = model_name
        Chains.setLlm(
            self.model_name, self.openai_api_key, openai_api_base=self.openai_api_base
        )

    def __repr__(self) -> str:
        return f"AutoPlanning(model_name='{self.model_name}',max_steps={self.max_steps})"

    def __call__(
        self,
        skill,
        description,
        save_file=''
    ):
        # phase1: skill -> plan
        instruction = f'{skill}: {description}'
        plan = Chains.plan(instruction)
        print('plan: \n', plan)

        yield {
            "stage": "plan",
            "completed": True,
            "percentage": 20,
            "done": False,
            "message": "Plan has been generated.",
        }

        # phase2: plan -> tasks
        task_list = Chains.tasks(instruction=instruction, plan=plan)

        yield {
            "stage": "task",
            "completed": True,
            "percentage": 50,
            "done": False,
            "message": "Tasks have been generated.",
            "tasks": task_list,
        }

        # phase3: generate tasks params
        task_tweaks = []
        for task in task_list:
            task_type = task['task_type']
            components = copy.deepcopy(TASK2COMPONENTS[task_type])
            tweaks = defaultdict(dict)
            task_require_params = []
            for component in components:
                component_params = COMPONENT_PARAMS[component]
                component_require_params = component_params['require']
                component_option_param = component_params['option']

                for option_param, value in component_option_param.items():
                    tweaks[component][option_param] = value

                # only require params need to input by user
                for require_param, value in component_require_params.items():
                    task_require_params.append({'component': component,
                                                'param': require_param,
                                                'type': value})

            print(f'''task:{task['step']}, description: {task['description']}, 请输入task相关参数: ''')
            while task_require_params:
                param = task_require_params.pop(0)
                input_ = input(f"component name: {param['component']}, param name: {param['param']}, 请配置参数值: ")
                input_ = param['type'](input_)
                param['value'] = input_
                print(param)
                tweaks[param['component']][param['param']] = param['value']

            task_tweaks.append(tweaks)

        # phase4: tasks -> chain graph
        graph_generator = GraphGenerator(task_list, task_tweaks, skill=skill, description=description)
        agent_graph = graph_generator.build_graph()
        with open(save_file, 'w') as f:
            json.dump(agent_graph, f, ensure_ascii=False, indent=2)

