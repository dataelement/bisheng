"""Disposable, bounded tuple ordering for newly captured native inventories."""

import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.unification_progress import report_progress
from bisheng.permission.application.migration_read import OriginalTupleFact


async def stable_original_tuples(facts, *, current):
    """Keep original frozen bytes untouched; sort only new capture streams."""
    with TemporaryDirectory(prefix="f118-tuples-") as directory:
        path = Path(directory) / "facts.sqlite"
        database = sqlite3.connect(path)
        path.chmod(0o600)
        try:
            database.execute("PRAGMA cache_size=-4096")
            database.execute("PRAGMA temp_store=FILE")
            database.execute(
                "CREATE TABLE facts (user TEXT NOT NULL, relation TEXT NOT NULL, object TEXT NOT NULL, "
                "PRIMARY KEY(user,relation,object)) WITHOUT ROWID"
            )
            pending, processed = [], 0
            async for fact in facts:
                current()
                if type(fact) is not OriginalTupleFact or any(
                    type(value) is not str for value in (fact.user, fact.relation, fact.object)
                ):
                    raise KnowledgeOperationPlanConflictError(reason="migration_inventory_original_tuple_type")
                pending.append((fact.user, fact.relation, fact.object))
                if len(pending) == 200:
                    database.executemany("INSERT INTO facts VALUES(?,?,?)", pending)
                    processed += len(pending)
                    pending.clear()
                    report_progress("history_fga_sort", processed=processed, unit="tuple", waiting="read")
            if pending:
                database.executemany("INSERT INTO facts VALUES(?,?,?)", pending)
                processed += len(pending)
            database.commit()
            report_progress("history_fga_sort", processed=processed, total=processed, unit="tuple", waiting="complete")
            for values in database.execute("SELECT user,relation,object FROM facts ORDER BY user,relation,object"):
                current()
                yield OriginalTupleFact(*values)
        except sqlite3.IntegrityError as error:
            raise KnowledgeOperationPlanConflictError(reason="migration_inventory_duplicate_original_tuple") from error
        finally:
            database.close()
