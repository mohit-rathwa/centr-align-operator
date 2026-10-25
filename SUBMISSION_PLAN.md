# Submission plan — target October 25

The current date is October 23, 2026. The uploaded JD file itself states **October 20, 2026 at 5:30 PM IST**. This plan assumes you have separately confirmed an extension to October 25; verify the latest instruction before relying on the new date.

## October 23 — freeze the scope

- [x] Implement the invoice → policy gate → AP ledger → verification workflow.
- [x] Add approval/rejection, retries, duplicate safety, persisted state and audit trace.
- [x] Add an interactive UI, API docs, architecture notes and demo recording script.
- [x] Run the automated suite; the latest verified result is 10 passing tests.
- [ ] Run the UI locally yourself and confirm the expected demo behavior on your machine.
- [ ] Initialize your own Git repository, inspect `.env` / secrets, and create a clean commit.

## October 24 — verify and record

- [ ] Push to a public or interviewer-accessible GitHub repository.
- [ ] Follow `demo/DEMO_SCRIPT.md` and record a 2–3 minute walkthrough.
- [ ] Show all three proof points: successful completion, approval before write, and a retried fault; if time permits show duplicate protection.
- [ ] Run `pytest -q backend/tests` immediately before recording and preserve the passing output.
- [ ] Read `docs/FOUNDING_ENGINEER_WALKTHROUGH.md`; be ready to explain the trade-offs and limitations without overstating the prototype.
- [ ] Verify the form accepts a repository/video URL, plus any required role selection.

## October 25 — submit early

- [ ] Check the latest email/form deadline and timezone.
- [ ] Open the GitHub repository in a private/incognito window to confirm it is accessible.
- [ ] Check the README run instructions from a clean environment if feasible.
- [ ] Submit the repository and demo video, then save the confirmation.

## Do not spend the remaining time on

Do not attempt general desktop automation, add several new workflows, or spend hours deploying a public live service. Those are riskier than improving the reliability of this narrow proof. Make the existing behavior work, prove it clearly, and be able to explain why its boundaries are deliberate.
