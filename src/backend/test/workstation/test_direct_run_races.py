"""F004 code review: three races of a direct run's ending.

* A stop that arrives after the question was asked and before the run parked
  must end the run, not park it (the resumed run would stop on the answer).
* One failed stop/lease poll (a Redis hiccup) must not fail the run.
* A run that finishes after another caller declared it dead writes nothing:
  that caller already saved its partial answer (design §5 #24).

The REAL graph runs with the scripted model of ``test_direct_run``.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from bisheng.workstation.domain.services import run_lease as rl
from test.workstation.test_direct_run import ASK, CID, make_env  # noqa: F401  (fixture)


async def test_stop_before_parking_ends_the_run_instead_of_parking(make_env):  # noqa: F811
    env = make_env([ASK])
    ctx = await env.submit("帮我选颜色")
    real_park = env.lease.park

    async def park_after_a_stop(conversation_id, run_id):
        raise AssertionError("a stopped run must not park")

    env.lease.park = park_after_a_stop
    # The stop lands while the model asks: the watcher has not polled yet.
    real_feed_question = ASK

    async def ask_then_stop(messages):
        await env.lease.request_stop(ctx.run_id, CID)
        return real_feed_question

    env.model.script = [ask_then_stop]

    outcome = await env.run(ctx)

    assert outcome.status == "stopped"
    types = await env.types()
    assert types[-1] == "run_stopped"
    assert (await env.state()).status == rl.STATUS_IDLE
    assert env.finished == [(CID, ctx.run_id)]
    env.lease.park = real_park


async def test_one_failed_poll_does_not_fail_the_run(make_env):  # noqa: F811
    calls = {"n": 0}

    async def slow_answer(messages):
        # Give the watcher several polls while the model "thinks".
        for _ in range(3):
            await env._sleep(1)
        return AIMessage(content="答案")

    env = make_env([slow_answer])
    ctx = await env.submit("你好")
    real_should_stop = env.lease.should_stop

    async def flaky_should_stop(run_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("redis hiccup")
        return await real_should_stop(run_id)

    env.lease.should_stop = flaky_should_stop

    outcome = await env.run(ctx)

    assert outcome.status == "finished"
    assert calls["n"] >= 2
    assert (await env.types())[-1] == "run_finished"


async def test_run_that_was_declared_dead_writes_no_ending(make_env):  # noqa: F811
    async def answer_after_being_declared_dead(messages):
        # Another node found the lease lapsed and reported the run.
        env.clock.now += rl.LEASE_SECONDS + 1
        await env.dispatch.recover_expired(CID)
        return AIMessage(content="迟到的答案")

    env = make_env([answer_after_being_declared_dead])
    ctx = await env.submit("你好")

    outcome = await env.run(ctx)

    assert outcome.status == "lease_lost"
    types = await env.types()
    assert "run_finished" not in types
    # Only the failure the other caller reported ends the run on the stream.
    assert types.count("run_failed") <= 1
    assert not [e for e in env.hook_events if e["type"] == "run_finished"]


async def test_a_redis_error_while_confirming_the_lease_still_writes_the_answer(make_env):  # noqa: F811
    env = make_env([AIMessage(content="答案")])
    ctx = await env.submit("你好")
    real_renew = env.lease.renew
    calls = {"n": 0}

    async def renew_fails_at_the_end(conversation_id, run_id):
        calls["n"] += 1
        if calls["n"] > 1:  # the first renew claims the run; the last one confirms it
            raise ConnectionError("redis hiccup")
        return await real_renew(conversation_id, run_id)

    env.lease.renew = renew_fails_at_the_end

    outcome = await env.run(ctx)

    assert outcome.status == "finished"
    assert (await env.types())[-1] == "run_finished"


async def test_a_redis_error_while_reading_the_stop_flag_still_parks(make_env):  # noqa: F811
    env = make_env([ASK])
    ctx = await env.submit("帮我选颜色")

    async def should_stop_fails(run_id):
        raise ConnectionError("redis hiccup")

    env.lease.should_stop = should_stop_fails

    outcome = await env.run(ctx)

    assert outcome.status == "waiting"
    assert (await env.state()).status == rl.STATUS_WAITING
