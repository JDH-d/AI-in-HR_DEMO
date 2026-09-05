# PeopleFlow UI redesign — design QA

Date: 2026-09-05

## Scope and selected reference

The second image from the second exploration round is the sole reference for layout, components, hierarchy and interaction character. The first image supplies only the light palette. Both themes use the same interface. The existing employee, request, manager, knowledge administration and sign-in flows remain in the existing frontend.

- Main reference: the second image from the second exploration round (1586 × 992).
- Light palette reference: the first image from that round.
- Local application: <http://127.0.0.1:5173/employee>.

## Screenshot evidence and comparison method

Reference images and screenshot evidence were retained locally during review and are not bundled with this repository. The filenames below identify those captures.

The main source was normalized to 1440 × 900 for comparison with the desktop application at that viewport. The aspect-ratio adjustment is less than 0.1%. Screenshots and source were viewed together, including a focused crop of the assistant reply and inline request. Mobile was checked at 390 × 844. Screenshot dimensions below are pixels; comparison boards retain the captured pixel density without enlargement.

| Evidence | Dimensions | Purpose |
| --- | --- | --- |
| `comparison-dark.png` | 2880 × 936 | Reference and actual dark employee screen side by side, with 36 px labels |
| `comparison-draft.png` | 1020 × 435 | Reference and actual assistant/request region; crops use different scroll origins |
| `comparison-themes.png` | 2880 × 936 | Identical conversation and scroll position in settled dark/light themes |
| `reference-dark-normalized.png` | 1440 × 900 | Normalized source |
| `chat-final-dark-top.png`, `chat-final-light-top.png` | 1440 × 900 | Same conversation at scroll position zero |
| `chat-final-dark.png` | 1440 × 900 | Conversation bottom, including complete draft and composer |
| `pto-review-dark.png`, `request-details-light.png` | 1440 × 900 | Request review and submitted request details |
| `chat-mobile-dark.png`, `chat-mobile-light.png` | 390 × 844 | Mobile conversation and anchored composer |
| `navigation-mobile-light.png`, `sick-leave-mobile-light.png` | 390 × 844 | Mobile navigation and usable request form |
| `manager-dark.png`, `manager-light.png`, `manager-decision-dark.png` | 1280 × 720 | Manager inbox and decision flow |
| `knowledge-overview-light.png`, `quality-dark.png` | 1280 × 720 | Knowledge overview and quality view |
| `documents-light.png`, `documents-dark.png`, `settings-dark.png` | 1265 × 712 | Documents and assistant settings |

The application screenshots use real local demo responses and requests. The policy answer is longer than the illustrative reference, so the conversation scrolls. Existing source disclosure, feedback, request shortcuts, real dates and statuses are retained. These content differences are intentional and were assessed separately from visual fidelity. The draft crop compares the same component despite the different scroll position.

## Fidelity review

| Surface | Result |
| --- | --- |
| Layout and spacing | Compact 278 px navigation, 64 px header, restrained conversation column, right-aligned user messages, left-aligned assistant and inline request, anchored composer. Mobile navigation becomes a dialog without horizontal overflow. |
| Typography | Locally served Inter with a coherent scale. Assistant copy is 16 px, dates 20 px, controls remain readable. No oversized promotional headings. |
| Color and treatment | Dark navy with periwinkle actions follows the selected structural reference. Light uses warm off-white, putty and muted green with identical geometry. Borders, radii, shadows and status accents stay restrained. |
| Assets and icons | Consistent Phosphor icon family; four-point brand mark uses its standard duotone icon. This deliberately avoids approximating the reference's iridescent asset with custom drawings. |
| Content and interaction hierarchy | Question, answer, source, request review and send remain the primary sequence. Drafts are reviewed explicitly instead of interrupting the answer with an automatic drawer. All previous product areas remain accessible. |

No unresolved P0, P1 or P2 visual findings remain. An independent visual review of the selected reference and final desktop/mobile captures reached the same conclusion. Minor illustrative differences in the mark, real copy and feedback controls do not require further changes for this demo.

## Comparison and correction history

1. Initial employee comparison showed excessive content indentation and small text. Adjusted conversation width and spacing, assistant avatar to 48 px, body copy to 16 px, request width to 400 px and date hierarchy to 20 px. Recompared full-screen and focused request regions.
2. Shared card padding overrode explicit zero padding in tables. Default padding now applies only when the caller does not specify padding. Verified manager and document layouts.
3. Mobile navigation closed when expanding all requests and could unmount a request trigger before its action ran. Switched delegated closing from capture to bubbling, retained the menu for the expand control, and added a real dialog trigger for focus restoration. Verified in the browser and regression tests.
4. Creating a PTO request remounted the form when its new ID arrived. Kept the active form stable; verified the success state and automatic close after successful submission.
5. An early light screenshot captured a theme transition. Replaced it with a settled screenshot and rebuilt the two-theme comparison. No mixed-theme colors remain in the settled interface.
6. Final typography, responsive forms, decision controls and source disclosures were reviewed after these corrections. No further actionable fidelity changes were found.

## Functional and accessibility checks

Browser checks used the running local frontend and backend:

- Sign-in for employee, manager and knowledge administrator; theme switch and persistence.
- Employee answer streaming, source expand/collapse, new conversation and preserved history.
- PTO draft created from chat, explicit review, note edit, send, success state and manager approval. Updated status and decision timeline visible to the employee.
- Sick leave report and manager acknowledgement.
- Mobile chat in both themes, navigation open/close, focus return, expanded request list and opening a new request form. Forms and footer actions remain reachable without horizontal overflow.
- Knowledge overview, documents, quality and assistant settings navigation. Unsaved settings survive section changes; discard restores them. Test request displays the backend response.
- Labels, focus indicators, disabled states, visible errors, IME-safe Enter handling and reduced-motion styling checked in the implemented controls.
- Browser error/warning logs for all three role tabs were empty at final inspection.

Automated validation completed successfully:

- `npm test`: 8 test files, 30 tests passed.
- `npm run build`: passed.
- `npm run check`: passed, 45 files checked.
- `git diff --check`: passed during final verification.

Meaningful regressions cover theme persistence, streamed chat/source/draft behavior, explicit request review, new-conversation state, preserving composer text across theme changes, request form submission, and mobile navigation/focus behavior.

## Boundaries

The initial redesign changes frontend presentation and related interaction behavior. The later chat-deletion follow-up also adds an owner-scoped backend endpoint, as described below. Backend answer quality, the intentionally narrow demo knowledge coverage and Slack integration are outside these changes. Document upload/deletion and every production failure mode were not exhaustively exercised; existing controls and API wiring were retained.

## Follow-up polish from user screenshots

Applied the four requested refinements: semantic colors on Overview metric icons, 12 px horizontal padding on suggested questions, an unfilled ghost-style `New Chat` action, and the `Recents` section label. The empty-chat header uses the same `New Chat` wording.

Inspected employee and Overview screens in both themes at 1280 × 720. Confirmed that the new-chat button has a transparent background and no border when not hovered, question buttons have equal 12 px left/right padding, and all six metric icons resolve to the intended theme colors. Browser error/warning logs were empty. The five employee interaction tests, Biome check and `git diff --check` passed; no new tests were added for cosmetic changes.

## Chat deletion, navigation spacing and favicon follow-up

- Reduced the New Chat / Recents gap from 36 px (combined button and heading margins) to 16 px.
- Added a separate, keyboard-accessible trash action for each conversation: revealed on hover/focus on desktop, always visible at narrow widths or on touch devices. Chat selection remains a separate button.
- Added a compact confirmation dialog with initial focus on Cancel, visible error/retry behavior, and focus restoration to the original action or New Chat after deletion. Mobile navigation remains open when managing history.
- Implemented persistent owner-scoped deletion with an empty HTTP 204 response; wrong-owner and missing IDs return the same 404. Messages are removed with their conversation; workflow requests and their timeline remain independent. A one-time legacy import marker prevents deleted history reappearing after restart.
- Added an SVG favicon rendered directly from the same Phosphor StarFour duotone icon as BrandMark. Verified SVG delivery and the page's favicon link.

Browser verification covered the dark desktop confirmation, cancellation and focus return, the light mobile navigation and confirmation at 390 × 844, and successful removal of a newly created temporary QA conversation. After deleting the active chat, the workspace showed New Chat, navigation retained the three existing conversations, all four requests were unchanged, and focus returned to New Chat. No horizontal overflow was present. The temporary QA chat was the only conversation deleted during browser verification.

Final checks: frontend build passed; 35 frontend tests passed; Biome checked 46 files successfully; 28 backend tests plus 2 subtests passed; targeted Ruff and `git diff --check` passed.

final result: passed
