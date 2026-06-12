"""F035 Wave-0 shared fixtures & stubs (Track 0 / Lead deliverable).

These artifacts freeze the cross-Track contracts so every Track can program
against a stub/mock instead of waiting for the producing Track:

- ``fake_workspace_backend.FakeWorkspaceBackend`` — C2 stub (A / B / H).
- ``ws_events/*.json`` — C1 WebSocket event fixtures (A writes mapping
  assertions, H renders against the same JSON — one source of truth).
- ``skill_api_mock.json`` — C3 Skill API mock responses (I).

See ``README.md`` and ``features/v2.6.0/035-linsight-task-mode/依赖与契约约定.md``.
"""
