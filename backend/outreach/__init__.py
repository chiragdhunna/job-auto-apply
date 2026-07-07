"""Recruiter / hiring-manager outreach — DRAFT-ONLY by design.

This package identifies likely contacts and drafts personalized messages.
It NEVER sends anything: no LinkedIn automation, no SMTP, no send toggles.
The owner reviews and sends every message manually. `mark-sent` endpoints are
status bookkeeping only. This is a deliberate architectural constraint —
see backend/outreach/contact_finder.py and message_drafter.py docstrings.
"""
