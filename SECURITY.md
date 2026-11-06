# Security Policy

## Reporting a Vulnerability

Please report security vulnerabilities to us privately, and **not** through public
GitHub issues, discussions or pull requests.

Use GitHub's private reporting:
[**Report a vulnerability**](https://github.com/dataelement/bisheng/security/advisories/new)

This opens a draft advisory visible only to you and the maintainers. We can discuss
the details, share a patch, and publish the advisory together once a fix is out.

### What to include

- Reproducible steps, and a proof of concept if you have one
- The version or commit hash you tested
- Any mitigation or workaround you already know of

### What to expect

| | |
|---|---|
| We acknowledge your report | within **3 business days** |
| We tell you whether we can reproduce it, and how we rate it | within **10 business days** |
| We keep you updated while a fix is being prepared | at least every 2 weeks |
| We credit you in the advisory and the release notes | unless you ask us not to |

If you have not heard from us within those windows, the report has fallen through
a crack rather than been dismissed — please say so in the draft advisory, or open a
public issue asking us to look at it.

### Disclosure

We ask for a 90-day window before public disclosure, and we would rather publish
sooner: once a fix has shipped we publish the advisory and request a CVE.

If a report goes unanswered past the windows above, we do not expect you to keep
waiting. That has happened before and it was our failure, not yours.

## Supported Versions

Security fixes land on the current release line. Older lines receive fixes only for
vulnerabilities rated critical, and only while they are still in support.

| Version | Supported |
|---------|-----------|
| 3.0.x (current release line) | ✅ |
| 2.6.x | Critical fixes only |
| Earlier releases | ❌ |

---
Last updated: September 2026
