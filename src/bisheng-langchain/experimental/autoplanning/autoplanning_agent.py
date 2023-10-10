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
        openai_api_base="",
    ):
        assert len(
            openai_api_key.strip()
        ), "Either give openai_api_key as an argument or put it in the environment variable"
        self.model_name = model_name
        self.openai_api_key = openai_api_key
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
        return f"AutoPlanning(model_name='{self.model_name}')"

    def __call__(
        self,
        skill,
        description,
        save_file='',
        global_params={},
        input_required_params=False,
    ):
        # phase1: skill -> plan
        print('-----------phase1: skill -> plan--------------------')
        instruction = f'{skill}: {description}'
        plan = Chains.plan(instruction)

        print({
            "stage": "plan",
            "completed": True,
            "percentage": 20,
            "done": False,
            "message": "Plan has been generated.",
            "plan": plan
        })

        # phase2: plan -> tasks
        print('-----------phase2: plan -> tasks--------------------')
        task_list = Chains.tasks(instruction=instruction, plan=plan)

        print({
            "stage": "task",
            "completed": True,
            "percentage": 50,
            "done": False,
            "message": "Tasks have been generated.",
            "tasks": task_list,
        })

        # phase3: generate tasks params and some params update by global param or user input (openai_api_key)
        print('-----------phase3: generate tasks params--------------------')
        task_tweaks = []
        for task in task_list:
            task_type = task['task_type']
            components = copy.deepcopy(TASK2COMPONENTS[task_type])
            tweaks = defaultdict(dict)
            task_require_params = []
            for component in components:
                if component not in COMPONENT_PARAMS:
                    continue
                component_params = COMPONENT_PARAMS[component]
                component_require_params = component_params['require']
                component_option_param = component_params['option']

                for option_param, value in component_option_param.items():
                    tweaks[component][option_param] = value

                # required params update by global param
                for require_param, value in component_require_params.items():
                    task_require_params.append({'component': component,
                                                'param': require_param,
                                                'type': value})
                    # required params initial by global params
                    if require_param in global_params:
                        param_value = global_params[require_param]
                        if param_value and isinstance(param_value, list):
                            tweaks[component][require_param] = param_value.pop(0)
                        elif param_value:
                            tweaks[component][require_param] = param_value

            # required params update by user input
            if input_required_params:
                print(f'''task:{task['step']}, description: {task['description']}, 请输入task相关参数: ''')
                while task_require_params:
                    param = task_require_params.pop(0)
                    input_ = input(f"component name: {param['component']}, param name: {param['param']}, 请配置参数值: ")
                    input_ = param['type'](input_)
                    param['value'] = input_
                    print(param)
                    tweaks[param['component']][param['param']] = param['value']

            task_tweaks.append(tweaks)

        print({
            "stage": "parameters input",
            "completed": True,
            "percentage": 70,
            "done": False,
            "message": "Task parameters have been generated.",
            "task_tweaks": task_tweaks,
        })

        # phase4: tasks -> langflow graph
        print('-----------phase4: tasks -> langflow graph--------------------')
        graph_generator = GraphGenerator(task_list, task_tweaks, skill=skill, description=description)
        agent_graph = graph_generator.build_graph()
        if save_file:
            with open(save_file, 'w') as f:
                json.dump(agent_graph, f, ensure_ascii=False, indent=2)

        print({
            "stage": "graph",
            "completed": True,
            "percentage": 100,
            "done": True,
            "message": "Langflow graph have been generated.",
        })

        return agent_graph

