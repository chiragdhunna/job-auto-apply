"""Job scrapers.

`base` defines the abstract interface + shared parsing/matching helpers.
`ats_boards_scraper` implements the low-detection public-API scrapers
(Greenhouse / Lever / Ashby, plus a best-effort Workday helper).
`indeed_scraper` / `linkedin_scraper` are browser-driven and implemented
alongside their automation modules (Phases 10-11).
"""
