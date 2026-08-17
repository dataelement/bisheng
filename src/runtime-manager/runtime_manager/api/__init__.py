"""HTTP surface of the runtime manager.

``intents`` — the write side the backend drives (build / deploy / stop /
destroy / probe / admission). ``routes`` — the read side the app-proxy drives
(upstream resolution). ``readonly`` — status / logs / runtime-status (T031).
"""
