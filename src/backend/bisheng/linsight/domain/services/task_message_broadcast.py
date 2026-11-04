"""Fan out the existing task queue to every connected viewer across API workers."""

import asyncio
import pickle
from contextlib import asynccontextmanager

# Redis executes delivery and acknowledgement together. Writers retain their
# existing queue contract, and viewers receive each frame in the same order.
_BROADCAST_NEXT = """
local message = redis.call('LINDEX', KEYS[1], 0)
if not message then return 0 end
local viewers = redis.call('PUBLISH', ARGV[1], message)
if viewers > 0 then redis.call('LPOP', KEYS[1]) end
return viewers
"""


@asynccontextmanager
async def task_message_subscription(redis, queue_key: str):
    """Subscribe before draining so simultaneous viewers share every new frame."""
    channel = f"{queue_key}:broadcast"
    async with redis.pubsub() as subscription:
        await subscription.subscribe(channel)
        # subscribe() writes the command; its acknowledgement establishes the
        # ordering barrier before this connection can publish queued frames.
        async with asyncio.timeout(5):
            while True:
                acknowledgement = await subscription.get_message(timeout=5)
                if acknowledgement and acknowledgement["type"] == "subscribe":
                    break

        async def messages():
            while True:
                # One key keeps this command compatible with Redis Cluster.
                await redis.eval(_BROADCAST_NEXT, 1, queue_key, channel)
                frame = await subscription.get_message(ignore_subscribe_messages=True, timeout=1)
                yield pickle.loads(frame["data"]) if frame and frame["type"] == "message" else None

        yield messages()
