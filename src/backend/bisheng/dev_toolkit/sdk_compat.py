"""The platform's declared compatibility floor for ``bisheng-sdk`` (F057 D16).

This is a **platform** statement, not the SDK's own version: "applications whose
locked ``bisheng-sdk`` is older than this will be refused on their first call".
The SDK version itself lives in ``bisheng_sdk.__version__`` and travels through
``scripts/pack_sdk_wheel.sh`` into ``artifacts/manifest.json``; the endpoints
read the manifest, never this module, because a version is a property of the
build rather than of the source tree.

⚠️ Raising this constant declares every application pinned below it broken at
its next ``retrieve`` / ``storage`` call — the SDK raises ``SdkIncompatibleError``
and the owner has to bump the dependency and redeploy (which is an approval,
INV-34). So it moves only when an old SDK genuinely cannot talk to this
platform, never as routine version hygiene.
"""

SDK_MIN_COMPATIBLE = "0.1.0"
