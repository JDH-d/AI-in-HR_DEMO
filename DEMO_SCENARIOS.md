п»ї# Demo Scenarios

## Employee Flow
1. Sign in as `employee` with the configured demo password.
2. Ask: `What can you help with?`
3. Select: `1` or `PTO`
4. Ask: `How far in advance should I request vacation?`
5. Ask: `Can I request partial-day PTO?`
6. Prepare a request: `I need vacation from 2030-04-10 to 2030-04-12`
7. Review the extracted fields and click **Submit request**.
8. Open **My Requests** and show the status history.

## Manager Flow
1. Sign out and sign in as `manager` with the configured demo password.
2. Open the employee request in the inbox and choose **Start review**.
3. Choose **Approve** or **Reject**, provide a reason and relevant policy criteria, confirm equal treatment, then confirm the decision.
4. Return to Employee → All requests and open the request to see the reason, criteria, comments and timeline.
5. Choose **Request reconsideration**, explain why, and return to Manager to review the new round. The original decision remains visible.
6. For an approved request, Manager can choose **Mark completed** and record what was delivered.
7. Test **Request information** / **Provide information**, a private TXT attachment, search and priority/status filters.

## Knowledge Admin Flow
1. Sign in as `knowledge_admin`.
2. Inspect metrics and the Documents area.
3. Upload or index a document, then inspect its indexing status.
4. Review rated answers and unanswered questions in the Quality queue.
5. Preview an unsaved system prompt and AI settings before saving.

## Suggested Narrative
- Start with employee self-service.
- Show policy-grounded answers rather than generic LLM output.
- Transition into draft preparation and explicit confirmation.
- End with protected manager transitions and auditability.
