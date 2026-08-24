# Security policy

## Reporting a vulnerability

If you believe you have found a security vulnerability in FamilyBoard CalDAV,
please **do not open a public issue**. Instead, report it privately via GitHub's
[private vulnerability reporting](https://github.com/apiest/ha-familyboard-caldav/security/advisories/new)
form.

You can expect:

- An acknowledgement within a reasonable time (this is a personal,
  best-effort project — there is no SLA).
- A coordinated disclosure timeline once the issue is triaged.

## Supported versions

Only the latest released version of FamilyBoard CalDAV receives fixes. Older
versions are not patched.

## Scope

In scope:

- The Home Assistant custom integration code under
  `custom_components/familyboard_caldav/`.

Out of scope:

- Vulnerabilities in Home Assistant itself — please report those to the
  [Home Assistant project](https://www.home-assistant.io/security/).
- Vulnerabilities in the upstream `caldav` Python library — report those
  to the library maintainers.
- Misconfiguration of a user's own Home Assistant instance.
