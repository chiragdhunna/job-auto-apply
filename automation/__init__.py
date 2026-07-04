"""Browser automation (Playwright).

Shared launch/stealth config lives in `stealth_config`. Each platform has its own
applier: `ats_apply` (Greenhouse/Lever), `linkedin_apply`, `indeed_apply`.

These modules run a NON-headless, persistent browser context on the owner's own
machine, using their own logged-in sessions. They are intentionally not run in
CI / the backend request path.
"""
