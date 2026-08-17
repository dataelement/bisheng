"""BiSheng hosted-app runtime manager.

Standalone package (F054 D1): lives outside ``src/backend/bisheng`` and never
imports ``bisheng``. It is the *only* component in the product that holds an
orchestration backend access face (dockerd today, k8s in F059) — see
``scripts/arch-guard.sh`` RULE-10 for the machine-enforced counterpart on the
backend side.

The backend talks to this process over intent-style HTTP RPC signed with HMAC
(``src/backend/bisheng/app_runtime/domain/services/orchestrator_client.py``).
Every public interface is deliberately *form agnostic*: no ``container`` /
``compose`` word appears in a request or response field name (INV-33).
"""

__version__ = "3.0.0"
