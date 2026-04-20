"""F015 AC-08 performance harness (placeholder).

Target: ``OrgReconcileService.reconcile_config`` processes a 100k-dept
remote snapshot in under 30 minutes on a standard production-equivalent
MySQL + Redis + 1 Celery worker.

Status: NOT wired to CI. Scheduled to run ~2 weeks before the v2.5.1
release on a dedicated preprod environment. Baselines go into
``features/v2.5.1/015-ldap-reconcile-celery/ac-verification.md``
section 4.

Intended usage:

.. code-block:: bash

    # 1. Stand up preprod MySQL + Redis + bisheng worker
    # 2. Seed ``org_sync_config`` with one ``provider='test_bulk'`` row
    # 3. Run this script to generate the 100k-dept DTO set and invoke
    #    reconcile via a fake provider
    python scripts/performance/locust_ldap_reconcile_100k.py --config-id 1

The script will be fleshed out in the pre-release sprint with:

* Fake provider (``OrgSyncProvider`` subclass) that returns a 2-level
  tree of 100 roots x 1000 leaves.
* Timing harness capturing wall time, MySQL/Redis CPU, Celery worker
  RSS.
* CSV baseline output under ``scripts/performance/baselines/``.
"""

if __name__ == '__main__':
    raise SystemExit(
        'F015 AC-08 perf harness is not implemented yet. Schedule a '
        'preprod window ~2 weeks before v2.5.1 release and flesh this '
        'script out per the docstring plan.'
    )
