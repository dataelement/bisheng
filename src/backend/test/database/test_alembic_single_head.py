"""Guard: the alembic migration graph must always have exactly one head.

Why:
  Migrations chain via ``down_revision``. If a new revision's ``down_revision``
  is mounted on an already-applied (old) revision instead of the current head,
  the graph forks into >1 head. ``alembic upgrade head`` (run at API startup in
  ``entrypoint.sh``) then aborts with "Multiple head revisions are present", and
  the container would otherwise start on a stale, half-migrated schema. This
  test catches the fork at PR/CI time, before it ever reaches a database.

  Runs fully offline: ``ScriptDirectory`` parses the version files only — it does
  not import ``env.py`` or open a DB connection.
"""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

# test/database/test_alembic_single_head.py -> parents[2] == src/backend
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _script_directory() -> ScriptDirectory:
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    # Resolve script_location to an absolute path so the check is independent of
    # the pytest working directory (alembic resolves it relative to cwd).
    cfg.set_main_option(
        "script_location",
        str(_BACKEND_ROOT / "bisheng" / "core" / "database" / "alembic"),
    )
    return ScriptDirectory.from_config(cfg)


def test_single_alembic_head():
    heads = _script_directory().get_heads()
    assert len(heads) == 1, (
        f"Expected exactly one alembic head, found {len(heads)}: {heads}.\n"
        "A new migration's down_revision was likely mounted on an already-applied "
        "revision instead of the current head, forking the migration graph. "
        "Re-point down_revision to the real head (run 'alembic heads' to find it), "
        "or — if the branches are intentional — add a merge revision via "
        "'alembic merge heads'."
    )
