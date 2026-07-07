"""Reset the database for a fresh start.

Deletes ALL jobs, applications, resume versions, and outreach contacts/drafts.
By default also deletes the generated resume PDFs, but KEEPS your dashboard
settings (score threshold, source toggles, run interval). The schema stays in
place — no re-init needed.

Usage (stop ./run.sh first so the scheduler isn't writing mid-wipe):

    python reset_db.py                  # interactive: type DELETE to confirm
    python reset_db.py --yes            # no prompt (for Git Bash/mintty, where
                                        #   interactive stdin often doesn't work)
    python reset_db.py --yes --keep-pdfs        # keep generated resume PDFs
    python reset_db.py --yes --reset-settings   # also reset dashboard settings
                                                #   to keywords.yaml defaults

This cannot be undone. Back up data/jobs.db first if you might want it later.
"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Wipe all job data for a fresh start.")
    parser.add_argument("--yes", action="store_true",
                        help="skip the interactive confirmation")
    parser.add_argument("--keep-pdfs", action="store_true",
                        help="keep generated resume PDF files in data/resumes/")
    parser.add_argument("--reset-settings", action="store_true",
                        help="also reset dashboard settings to keywords.yaml defaults")
    args = parser.parse_args()

    if not args.yes:
        print("This will permanently delete ALL jobs, applications, resume versions,")
        print("and outreach drafts" + ("" if args.keep_pdfs else " + generated resume PDFs") + ".")
        if args.reset_settings:
            print("Dashboard settings will ALSO be reset to keywords.yaml defaults.")
        try:
            answer = input('Type DELETE to confirm: ').strip()
        except EOFError:
            # Git Bash / mintty often gives Python no interactive stdin.
            print("\nNo interactive terminal detected — nothing was deleted.")
            print("Re-run with:  python reset_db.py --yes")
            return 2
        if answer != "DELETE":
            print("Confirmation not received — nothing was deleted.")
            return 1

    from backend.db.session import SessionLocal, init_db
    from backend.db import crud

    init_db()  # ensure schema exists (also makes this safe on a brand-new clone)
    db = SessionLocal()
    try:
        counts = crud.clear_all_data(db, include_settings=args.reset_settings)
    finally:
        db.close()

    pdf_count = 0
    if not args.keep_pdfs:
        from backend.resume_tailor.latex_engine import RESUME_DIR
        if RESUME_DIR.exists():
            for f in RESUME_DIR.iterdir():
                if f.is_file():
                    try:
                        f.unlink()
                        pdf_count += 1
                    except OSError as exc:
                        print(f"  ! could not delete {f.name}: {exc}")

    print("Fresh start complete:")
    print(f"  jobs deleted:              {counts.get('jobs', 0)}")
    print(f"  applications deleted:      {counts.get('applications', 0)}")
    print(f"  resume versions deleted:   {counts.get('resume_versions', 0)}")
    print(f"  outreach drafts deleted:   {counts.get('outreach_drafts', 0)}")
    print(f"  outreach contacts deleted: {counts.get('outreach_contacts', 0)}")
    if not args.keep_pdfs:
        print(f"  resume PDF files deleted:  {pdf_count}")
    if args.reset_settings:
        print(f"  settings reset:            {counts.get('settings', 0)} entries")
    else:
        print("  dashboard settings:        kept (use --reset-settings to reset)")
    print("\nStart everything again with ./run.sh — discovery begins from scratch.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
