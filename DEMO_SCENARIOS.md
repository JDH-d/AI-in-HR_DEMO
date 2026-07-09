# Demo Scenarios

## Employee Flow
1. Ask: `What can you help with?`
2. Select: `1` or `PTO`
3. Ask: `How far in advance should I request vacation?`
4. Ask: `Can I request partial-day PTO?`
5. Create a request: `I need vacation from 04/10 to 04/12`
6. Confirm that the assistant creates a workflow request and returns the request ID.

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
6. Load workflow requests and update one request status from `pending` to `approved`.

## Teams Flow
1. Open the personal chat with the Teams bot.
2. Type: `help`
3. Ask: `How often are salaries paid?`
4. Ask: `How do I request VPN access?`
5. Confirm that answers include a `Sources` block when document retrieval is used.
6. Type: `clear` to reset the Teams chat history.

## Suggested Narrative
- Start with employee self-service.
- Show policy-grounded answers rather than generic LLM output.
- Transition into workflow creation.
- End with administration and auditability.
- If useful, close with the Teams personal bot to show multi-interface support.
