"""Opt-in F059 real platform publication and owner-data regression.

F059_E2E=1 is mandatory. Test identities and packages must belong to a dedicated
non-root tenant, and have e2e-f059- names. The CLI provides staged resume and
operator-driven restart checkpoints. No cluster/API execution is mocked here.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from test.e2e.helpers.vibe_runtime import EvidenceJournal, LiveVibeSuite, SuiteSettings

pytestmark = pytest.mark.skipif(os.environ.get("F059_E2E") != "1", reason="requires dedicated live F059 deployment")


@pytest.mark.asyncio(loop_scope="class")
class TestE2EVibeKubernetesRuntime:
    @pytest_asyncio.fixture(scope="class", loop_scope="class")
    async def suite(self, tmp_path_factory):
        settings = SuiteSettings.from_env()
        evidence = Path(os.environ.get("F059_E2E_EVIDENCE", str(tmp_path_factory.mktemp("f059") / "api-evidence.json")))
        journal = EvidenceJournal(evidence, tenant_code=settings.tenant_code)
        async with httpx.AsyncClient(
            timeout=75, trust_env=False, follow_redirects=False, verify=settings.ssl_context
        ) as client:
            live = LiveVibeSuite(settings, journal, client)
            await live.authenticate()
            await live.installation()
            await live.cleanup()
            try:
                for scenario in settings.scenarios:
                    await live.deploy(scenario)
                yield live
            finally:
                await live.cleanup()

    async def test_runtime_diagnostics_and_ordinary_owner_denial(self, suite):
        """AC-01, AC-30, AC-32: real public diagnostics allow super admin and deny owner."""
        await suite.installation()

    async def test_publication_permissions_and_owner_data(self, suite):
        """AC-04, AC-05, AC-10, AC-12, AC-24, AC-25, AC-33, AC-36, AC-46: real publication and paired denials."""
        for scenario in suite.settings.scenarios:
            if scenario.expected_failure_code is None:
                await suite.observe(scenario)

    async def test_stop_resume_and_iteration_keep_data(self, suite):
        """AC-29, AC-33, AC-35, AC-36, AC-44, AC-45: stop/resume and optional code update preserve data."""
        for scenario in suite.settings.scenarios:
            if scenario.expected_failure_code is not None:
                continue
            await suite.cycle(scenario)
            if scenario.update:
                await suite.deploy(scenario, update=True)
                await suite.observe(scenario)

    async def test_preapproval_failures_do_not_create_approval_or_version(self, suite):
        """AC-08, AC-09, AC-28: configured missing-material/image/health cases retain exact failure codes and stages."""
        negatives = [scenario for scenario in suite.settings.scenarios if scenario.expected_failure_code is not None]
        if not negatives:
            pytest.skip("no explicit negative package fixtures configured; failure ACs remain unverified")
        assert any(event["name"] == "preapproval-failure" for event in suite.journal.document["events"])
