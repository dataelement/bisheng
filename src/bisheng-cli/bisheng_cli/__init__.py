"""BiSheng developer CLI.

Single source of truth for the version: `--version`, the compatibility probe in
`http.py` and the `manifest.json` written by `scripts/pack_cli_wheel.sh` all read
`__version__` from here. Bumping it in two places is how the download endpoint
starts advertising a version that is not the one inside the wheel.
"""

__version__ = "3.0.0"
