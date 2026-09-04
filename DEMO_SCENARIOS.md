# PeopleFlow AI demo scenarios

Use the default password `demo-password` unless the local environment overrides it.

## 1. Grounded employee conversation

1. Sign in as `employee`.
2. Ask `When is payroll processed?`.
3. Open Sources and show the exact handbook evidence.
4. Ask the contextual follow-up `What if that date is a holiday?`.
5. Click the PeopleFlow logo. Point out that a fresh chat opens without adding an empty history item.
6. Reopen the payroll conversation from Recent conversations and show that both exchanges return.

## 2. PTO approval

1. In Employee Workspace, ask `I need vacation from 2030-04-10 to 2030-04-12` or click New request.
2. Review the dates, quick-length controls, planning note, and summary.
3. Send the request and show the short confirmation animation.
4. Sign in as `manager` and open the request marked In review.
5. Approve it, or decline it to demonstrate the required decision note.
6. Return as `employee`; open My requests and show the current status and timeline.
7. Reopen the original chat and show that its request card also reflects the current status.

## 3. Sick leave report

1. Sign in as `employee` and click New request.
2. Choose Sick leave.
3. Set the first day, expected return (or Not sure), and full/partial-day availability.
4. Optionally add a team note or flag a possible extended/recurring absence.
5. Submit the report. Explain that this shares availability directly; it is not an approval request.
6. Sign in as `manager`, open the Reported item, add an optional support note, and acknowledge it.
7. Show the final Acknowledged status and event timeline.

## 4. Ask HR demo interaction

1. In Employee Workspace, click Ask HR.
2. Explain that the response is deliberately fixed: the tech demo preserves the intended interaction without claiming to integrate with a real help desk.
3. Reopen it from conversation history to show that the exchange itself is real and persistent.

## 5. Knowledge operations

1. Sign in as `knowledge_admin`.
2. In Documents, upload a small `.md` file and show automatic indexing.
3. Use Rebuild index and point out whether the current mode is embedding or lexical fallback.
4. In Quality, inspect anonymized helpful/unhelpful feedback and unresolved knowledge gaps.
5. In AI settings, change an unsaved control, run the side-effect-free preview, then discard or apply it.
6. Return to Overview and refresh the metrics.

## Suggested narrative

- Start with trustworthy answers and real history.
- Move from chat into one approval workflow and one reporting workflow.
- Show that manager actions update the same underlying request everywhere.
- Finish with operational ownership: source maintenance, quality review, and safe configuration.
