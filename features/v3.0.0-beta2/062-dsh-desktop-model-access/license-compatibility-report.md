# F062 License compatibility evidence

Date: 2026-09-09. Gateway branch `feat/dsh-access`, baseline `main@75a74ff28ea95cba0938ff4912317cade2353337`. Status: **local regression verified; historical binary/issuer acceptance pending**. No customer License or vendor signing secret is stored in this report or test fixtures.

## Preserved behavior and executed checks

| Boundary | Evidence | Limit |
|---|---|---|
| Legacy RSA envelope | `LicenseLoader.checkDate` still invokes the existing RSA decrypt path before `applyDecoded` | Actual old ciphertext, RSA block sizes and issuer output were not supplied |
| Legacy trial expiration | `DshLicenseLoaderCompatibilityTest` covers expiration on the current expiry day and unchanged remaining-day semantics | Tests begin with decoded JSON; they are not ciphertext compatibility tests |
| Non-trial/pro | Historical non-trial version continues to resolve to pro; malformed DSH extension does not expire it | No new restrictions are imposed on the old commercial status |
| Expired trial + valid DSH | Signed fixture proves independent DSH activity while the old trial remains expired | A test signing key and fixture clock are used |
| DSH signature and binding | `DshEntitlementTest` exercises valid/invalid signed vectors, strict claims, outer-field binding, instance, expiry, schema and trusted key checks | These vectors are not vendor-issued customer Licenses |
| Existing paid routes | `LicenseStatusHolderTest`, `LicenseExpiredGlobalFilterTest`, `DshRoutingTest` retain the legacy HTTP 200 / status_code 11001 behavior while transferring only exact DSH routes to independent handling | This validates the current source and isolated Spring context |
| Activation and rollback | Real Redis activation and local CLI tests cover pause, replica acknowledgements, drain and resume; invalid/expired capability leaves read/revoke available | Deployment replica inventory, external fencing and real operator rollout remain site acceptance |

DSH uses a separately verified RS256 capability with full legacy outer-field binding. New DSH trust configuration does not reuse old License key material. No grant totals are added together across multiple License documents; an installation has one selected effective capability.

## T111 remains open

Required external inputs: the actual target old Gateway artifact and its SHA-256, the supported issuer/tool version, authorized old trial/pro ciphertext samples, and a new extended ciphertext issued through that same tool. Keep sample contents and credentials in restricted test storage; report only case labels, artifact hashes and observed status.

Run the same legacy samples through the target old and new binaries. Run new extended ciphertext through the target old binary, including near-limit plaintext lengths, multiple RSA blocks, Unicode, absent/unknown extension and invalid envelope. Confirm old paid behavior and rollback to the prior License separately from DSH capability validity. Record the exact commands with secret values supplied through protected configuration, process exit codes, API status and timestamps.

There is deliberately no placeholder `DshLegacyBinaryCompatibilityTest` claiming this proof. The existing `DshLicenseLoaderCompatibilityTest` is a decoded-input regression test. T111 must remain unchecked until the real artifact/issuer matrix is executed. Client contract 0.1.0 is unchanged.
