import asyncio
import importlib.metadata as md

from langgraph_sdk import get_client


async def main():
    c = get_client()  # url omitted, same call deepagents makes for an AsyncSubAgent without url
    print("deepagents", md.version("deepagents"), "| client base_url:", c.http.client.base_url)
    try:
        await c.threads.create()
        print("threads.create: OK")
    except Exception as e:
        print("threads.create FAILED:", type(e).__name__, str(e)[:120])


asyncio.run(main())
