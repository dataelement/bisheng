import asyncio
import os
import sys
from uuid import UUID

parent_dir = os.path.dirname(os.path.abspath(__file__)).replace('test', '')
sys.path.append(parent_dir)
os.environ['config'] = os.path.join(parent_dir, 'bisheng/config.dev.yaml')
from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.database.models.assistant import AssistantDao


async def test_init_tools():
    assistant = AssistantDao.get_one_assistant(UUID("379988576e884c62b3c2c4015245ddb6"))
    gpts_agent = AssistantAgent(assistant, "123")
    await gpts_agent.init_assistant()
    print(gpts_agent)


asyncio.run(test_init_tools())
