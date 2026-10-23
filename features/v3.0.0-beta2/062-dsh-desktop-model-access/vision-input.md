# DSH image input extension

Approved scope: a tenant administrator configures image input in DSH Desktop's model list.
The setting is independent of webpage workbench model settings and defaults to false.
The switch persists immediately, retains the confirmed value on failure, and exposes a retry.

Storage uses the existing configuration repository with a tenant/model-specific key.
Admin read/write reuses tenant-admin authorization and governed model visibility checks.
The Desktop model catalog adds `capabilities.vision`; chat rechecks it on every request.
Input supports inline PNG/JPEG/GIF/WebP, up to ten images, 5 MiB each and 20 MiB total.
External URLs remain outside the proxy contract. Image blocks are forwarded to the existing
governed LangChain provider and actual reported tokens follow existing usage accounting.
Automatic probing and changes to webpage model capabilities are outside this change.

Desktop's enterprise adapter consumes the capability, advertises image input and reads
verified attachment bytes through the Harness attachment service. Existing clients remain
text-only until upgraded. Server deployment does not distribute a Desktop installer.

Verification: protocol tests cover capability rejection, content forwarding, image validation,
tenant-separated storage and governed model checks. UI tests cover persistence and failures.
Real provider image recognition and native Desktop acceptance are separate acceptance gates.
