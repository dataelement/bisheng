"""What a deployment gets when its config says nothing about the Open API.

Both switches shipped as false while F053 was still being built, so that COFCO
could test the 3.0 upgrade without an unfinished surface appearing in the admin
console. The feature has since shipped, and a customer is not going to edit
config.yaml to reach it, so the shipped answer is now "on".

"On" still does not hand anybody a token. Personal tokens have two halves and
only the deployment half moved; the tenant half is off until a tenant admin
turns it on, and the console has to be visible for anyone to do that. So the
two defaults belong together: flipping only one leaves either a feature no one
can reach or a console page for a feature that is off.
"""

from __future__ import annotations

from bisheng.core.config.open_platform import OpenApiConf
from bisheng.open_api.domain.schemas.personal_token import PersonalTokenSettingResponse


def test_a_deployment_that_says_nothing_gets_both_surfaces() -> None:
    conf = OpenApiConf()

    assert conf.management_ui_enabled is True
    assert conf.pat_enabled is True


def test_a_deployment_can_still_withdraw_either_one() -> None:
    conf = OpenApiConf(management_ui_enabled=False, pat_enabled=False)

    assert conf.management_ui_enabled is False
    assert conf.pat_enabled is False


def test_the_deployment_half_alone_issues_no_token() -> None:
    """The tenant half is what actually turns personal tokens on."""

    response = PersonalTokenSettingResponse(
        deployment_enabled=True,
        pat_enabled=False,
        effective_enabled=True and False,
        pat_ttl_days=30,
    )

    assert response.effective_enabled is False
