# Demo Scenarios

## Employee Flow
1. Ask: `What can you help with?`
2. Select: `1` or `PTO`
3. Ask: `How far in advance should I request vacation?`
4. Ask: `Can I request partial-day PTO?`
5. Prepare a request: `I need vacation from 2030-04-10 to 2030-04-12`
6. Review the extracted fields and click **Confirm and submit**.
7. Open **My Requests** and show the status history.

## Manager Flow
1. Ask: `How do schedule changes work?`
2. Ask: `Do overtime hours require approval?`
3. Ask: `How should sick leave be reported?`
4. Use the response to explain manager review expectations and policy-backed answers.

## Admin Flow
1. Open the Streamlit admin console.
2. Load the current system prompt.
3. Refresh the document list.
4. Rebuild the vector index after a document change.
5. Load logs and show that user text can be masked.
6. Load workflow requests and move one from `submitted` to `in_review`.
7. Add a manager comment, then approve it and show the event history.

## Suggested Narrative
- Start with employee self-service.
- Show policy-grounded answers rather than generic LLM output.
- Transition into draft preparation and explicit confirmation.
- End with protected manager transitions and auditability.
