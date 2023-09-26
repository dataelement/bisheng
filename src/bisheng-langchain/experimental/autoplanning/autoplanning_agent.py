import os
import sys
import json
from time import sleep
from tqdm import trange
from planning_chain import Chains
from graph.graph import GraphGenerator


class AutoPlanning:

    def __init__(
        self,
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        model_name="gpt-3.5-turbo-16k-0613",
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
        print('plan:', plan)

        yield {
            "stage": "plan",
            "completed": True,
            "percentage": 20,
            "done": False,
            "message": "Plan has been generated.",
        }

        # phase2: plan -> tasks
        task_list = Chains.tasks(instruction=instruction, plan=plan)
        print('task_list:', task_list)

        yield {
            "stage": "task",
            "completed": True,
            "percentage": 50,
            "done": False,
            "message": "Tasks have been generated.",
            "tasks": task_list,
        }

        # phase3: tasks -> chain graph
        graph_generator = GraphGenerator(task_list, skill=skill, description=description)
        agent_graph = graph_generator.build_graph()
        with open(save_file, 'w') as f:
            json.dump(agent_graph, f, ensure_ascii=False, indent=2)


