# Demo Scenarios

## Employee Flow
1. Sign in as `employee` with the configured demo password.
2. Ask: `What can you help with?`
3. Select: `1` or `PTO`
4. Ask: `How far in advance should I request vacation?`
5. Ask: `Can I request partial-day PTO?`
6. Prepare a request: `I need vacation from 2030-04-10 to 2030-04-12`
7. Prepare a sick leave report: `I need sick leave tomorrow`
8. Review the extracted fields and submit or report the draft.
9. Open **My Requests** and show the status history.

## Manager Flow
1. Ask: `How do schedule changes work?`
2. Ask: `Do overtime hours require approval?`
3. Ask: `How should sick leave be reported?`
4. Use the response to explain manager review expectations and policy-backed answers.

## Admin Flow
1. Open the React application and choose an administration role.
2. Sign in as `manager`, load requests, approve or decline PTO, and acknowledge sick leave.
3. Add a manager comment and show the event history.
4. Sign out and sign in as `knowledge_admin`.
5. Refresh metrics and the document list.
6. Index one document and inspect masked logs.

## Suggested Narrative
- Start with employee self-service.
- Show policy-grounded answers rather than generic LLM output.
- Transition into draft preparation and explicit confirmation.
- End with protected manager transitions and auditability.
