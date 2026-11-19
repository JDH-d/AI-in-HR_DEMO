import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, Link, MemoryRouter, RouterProvider, useLocation, useNavigate } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { api } from "../../api/client";
import type { AISettingsResponse, Metrics } from "../../api/types";
import { UnsavedChangesProvider } from "../../components/UnsavedChanges";
import { DocumentsSection } from "./DocumentsSection";
import { KnowledgePage } from "./KnowledgePage";
import { OverviewSection } from "./OverviewSection";
import { QualitySection } from "./QualitySection";

vi.mock("../../api/client", () => ({ api: vi.fn(), downloadFile: vi.fn() }));
vi.mock("../../app/providers", () => ({ useAuth: () => ({ token: "test" }) }));
vi.mock("../../components/Shell", () => ({ Shell: ({children}: {children: ReactNode}) => <main>{children}</main> }));
vi.mock("../integrations/IntegrationsSection", () => ({ IntegrationsSection: () => <p>Integration settings</p> }));

const metrics: Metrics = {questions: 12, grounded_answer_rate: 75, unanswered_questions: 2, positive_feedback_rate: 80, requests_created: 4, requests_approved: 1};
const settings: AISettingsResponse = {settings: {strict_grounding:true, concise_answers:true, ask_clarifying_questions:true, suggest_next_steps:true, show_sources:true, auto_index_uploads:true}, system_prompt:"Saved instruction", default_system_prompt:"Default instruction"};
function client() { return new QueryClient({defaultOptions:{queries:{retry:false, staleTime:Infinity}, mutations:{retry:false}}}); }
function wrap(ui: ReactNode) { return render(<QueryClientProvider client={client()}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>); }
function defaultResult(path: string) {
  if (path.includes("metrics")) return {metrics};
  if (path.includes("ai-settings")) return settings;
  if (path.includes("documents")) return {documents: []};
  if (path.includes("feedback")) return {feedback: []};
  if (path.includes("unanswered")) return {questions: []};
  throw new Error("Unexpected test endpoint: " + path);
}
beforeEach(() => { vi.resetAllMocks(); vi.spyOn(window, "scrollTo").mockImplementation(() => {}); vi.mocked(api).mockImplementation(async path => defaultResult(path) as never); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("does not show zero metrics while loading and explains cached metrics after an error", () => {
  const {rerender} = render(<OverviewSection loading error={false} onRetry={vi.fn()} onNavigate={vi.fn()}/>);
  expect(screen.getByRole("status")).toHaveTextContent("Loading overview");
  expect(screen.queryByText("0")).not.toBeInTheDocument();
  rerender(<OverviewSection metrics={metrics} loading={false} error onRetry={vi.fn()} onNavigate={vi.fn()}/>);
  expect(screen.getByRole("alert")).toHaveTextContent("may be out of date");
  expect(screen.getByText("12")).toBeInTheDocument();
});

it("distinguishes a failed document load from an empty library and retries", async () => {
  let failed = true;
  vi.mocked(api).mockImplementation(async path => {
    if (path === "/api/v1/documents" && failed) throw new Error("Offline");
    return defaultResult(path) as never;
  });
  wrap(<DocumentsSection/>);
  expect(await screen.findByRole("alert")).toHaveTextContent("Unable to load documents");
  expect(screen.queryByText("No documents yet")).not.toBeInTheDocument();
  failed = false;
  fireEvent.click(screen.getByRole("button", {name:"Retry documents"}));
  expect(await screen.findByText("No documents yet")).toBeInTheDocument();
});

it("shows a quality load error instead of claiming that no answers need review", async () => {
  vi.mocked(api).mockImplementation(async path => {
    if (path.includes("feedback")) throw new Error("Offline");
    return defaultResult(path) as never;
  });
  wrap(<QualitySection metrics={metrics} onNavigate={vi.fn()}/>);
  expect(await screen.findByRole("alert")).toHaveTextContent("Unable to load feedback");
  expect(screen.queryByText("No answers need review")).not.toBeInTheDocument();
});

it("labels quality search, announces the selected view and distinguishes no matches", async () => {
  vi.mocked(api).mockImplementation(async path => path.includes("feedback") ? {feedback:[{id:"f", sentiment:"negative", rating:1, question:"VPN access", answer:"Ask support", comment:"Missing details", created_at:"2026-11-10T09:00:00Z"}]} as never : defaultResult(path) as never);
  wrap(<QualitySection metrics={metrics} onNavigate={vi.fn()}/>);
  await screen.findByRole("button", {name:"Review feedback: VPN access"});
  expect(screen.getByRole("button", {name:/Needs review/})).toHaveAttribute("aria-pressed", "true");
  fireEvent.change(screen.getByRole("textbox", {name:"Search quality records"}), {target:{value:"absent phrase"}});
  expect(screen.getByText("No matching records")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name:"Clear search"}));
  expect(screen.getByRole("button", {name:"Review feedback: VPN access"})).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name:/Knowledge gaps/}));
  expect(screen.getByRole("button", {name:/Knowledge gaps/})).toHaveAttribute("aria-pressed", "true");
  expect(await screen.findByText("No active knowledge gaps")).toBeInTheDocument();
});

it("offers a path from negative feedback to existing source management", async () => {
  const navigate = vi.fn();
  vi.mocked(api).mockImplementation(async path => path.includes("feedback") ? {feedback:[{id:"f", sentiment:"negative", rating:1, question:"VPN access", answer:"Ask support", comment:"Missing details", created_at:"2026-11-10T09:00:00Z"}]} as never : defaultResult(path) as never);
  wrap(<QualitySection metrics={metrics} onNavigate={navigate}/>);
  fireEvent.click(await screen.findByRole("button", {name:"Review feedback: VPN access"}));
  fireEvent.click(screen.getByRole("button", {name:"Review documents"}));
  expect(navigate).toHaveBeenCalledWith("documents");
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method)).toBe(false);
});

function NavigationControls() {
  const location = useLocation();
  const navigate = useNavigate();
  return <><output aria-label="Current location">{location.pathname + location.search}</output><Link to="/knowledge?section=documents">Go to documents</Link><button onClick={() => navigate(-1)}>Browser back</button></>;
}
function renderAdmin(entry: string) {
  const router = createMemoryRouter([{path:"*", element:<UnsavedChangesProvider><KnowledgePage/><NavigationControls/></UnsavedChangesProvider>}], {initialEntries:[entry]});
  return {router, ...render(<QueryClientProvider client={client()}><RouterProvider router={router}/></QueryClientProvider>)};
}

it("opens an admin section from its URL and browser back returns to the previous section", async () => {
  renderAdmin("/knowledge?section=quality");
  expect(screen.getByRole("heading", {name:"Answer quality"})).toBeInTheDocument();
  fireEvent.click(screen.getByRole("link", {name:"Go to documents"}));
  expect(await screen.findByRole("heading", {name:"Documents"})).toBeInTheDocument();
  expect(screen.getByLabelText("Current location")).toHaveTextContent("section=documents");
  fireEvent.click(screen.getByRole("button", {name:"Browser back"}));
  expect(await screen.findByRole("heading", {name:"Answer quality"})).toBeInTheDocument();
});

it("resets scroll and focuses the heading only when the admin section changes", async () => {
  const {router} = renderAdmin("/knowledge?section=settings");
  const question = await screen.findByRole("textbox", {name: "Test question"});
  expect(window.scrollTo).not.toHaveBeenCalled();
  expect(screen.getByRole("heading", {name: "AI settings"})).not.toHaveFocus();
  question.focus();
  fireEvent.change(question, {target: {value: "When is payroll?"}});
  expect(question).toHaveFocus();
  expect(window.scrollTo).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("link", {name: "Go to documents"}));
  const heading = await screen.findByRole("heading", {name: "Documents"});
  expect(heading).toHaveFocus();
  expect(window.scrollTo).toHaveBeenCalledExactlyOnceWith({top: 0});

  await screen.findByText("No documents yet");
  await act(async () => { await router.navigate("/knowledge?section=documents&view=library"); });
  fireEvent.click(screen.getByRole("button", {name: "Refresh"}));
  await waitFor(() => expect(screen.getByRole("button", {name: "Refresh"})).toBeEnabled());
  expect(window.scrollTo).toHaveBeenCalledTimes(1);
});

it("keeps unsaved settings when navigation is cancelled and discards only after confirmation", async () => {
  renderAdmin("/knowledge?section=settings");
  const concise = await screen.findByRole("checkbox", {name:/Keep answers concise/});
  fireEvent.click(concise);
  fireEvent.click(screen.getByRole("link", {name:"Go to documents"}));
  expect(await screen.findByRole("heading", {name:"Leave without saving?"})).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name:"Keep editing"}));
  expect(screen.getByRole("checkbox", {name:/Keep answers concise/})).not.toBeChecked();
  fireEvent.click(screen.getByRole("link", {name:"Go to documents"}));
  fireEvent.click(await screen.findByRole("button", {name:"Discard changes and leave"}));
  expect(await screen.findByRole("heading", {name:"Documents"})).toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method === "PUT")).toBe(false);
});

it("has an explicit system prompt label and does not call the AI service on opening settings", async () => {
  renderAdmin("/knowledge?section=settings");
  await screen.findByRole("checkbox", {name:/Keep answers concise/});
  fireEvent.click(screen.getByText("Advanced instructions"));
  await waitFor(() => expect(screen.getByLabelText("System prompt")).toHaveValue("Saved instruction"));
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method === "POST")).toBe(false);
});

it("discards a settings draft locally and applies only after the explicit command", async () => {
  vi.mocked(api).mockImplementation(async (path, _token, options) => options?.method === "PUT"
    ? {...settings, ...JSON.parse(String(options.body))} as never : defaultResult(path) as never);
  renderAdmin("/knowledge?section=settings");
  const concise = await screen.findByRole("checkbox", {name:/Keep answers concise/});
  const commands = screen.getByRole("region", {name:"Save assistant settings"});
  const apply = within(commands).getByRole("button", {name:"Apply settings"});
  expect(apply).toBeDisabled();
  fireEvent.click(concise);
  expect(apply).toBeEnabled();
  fireEvent.click(within(commands).getByRole("button", {name:"Discard"}));
  expect(concise).toBeChecked();
  expect(apply).toBeDisabled();
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method)).toBe(false);
  fireEvent.click(concise);
  fireEvent.click(apply);
  await waitFor(() => expect(commands).toHaveTextContent("Settings applied"));
  expect(concise).not.toBeChecked();
  const writes = vi.mocked(api).mock.calls.filter(call => call[2]?.method);
  expect(writes).toHaveLength(1);
  expect(writes[0][0]).toBe("/api/v1/admin/ai-settings");
  expect(writes[0][2]?.method).toBe("PUT");
  expect(JSON.parse(String(writes[0][2]?.body))).toMatchObject({settings:{concise_answers:false}, system_prompt:"Saved instruction"});
});

it("does not show one document's deletion error for a different document", async () => {
  const documents = ["First", "Second"].map((name, index) => ({id: String(index), name: `${name}.md`, title: `${name} policy`, category: "HR", version: "1", size: 100, modified: "2026-11-10", index_status: "indexed", chunk_count: 1, indexed_at: null, index_error: null}));
  vi.mocked(api).mockImplementation(async (path, _token, options) => {
    if (options?.method === "DELETE") throw new Error("First policy could not be removed.");
    return (path === "/api/v1/documents" ? {documents} : defaultResult(path)) as never;
  });
  wrap(<DocumentsSection/>);
  const first = (await screen.findByRole("heading", {name: "First policy"})).closest("article")!;
  fireEvent.click(within(first).getByText("More actions"));
  fireEvent.click(screen.getByRole("button", {name: "Remove document: First policy"}));
  fireEvent.click(screen.getByRole("button", {name: "Remove and rebuild"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("First policy could not be removed.");
  fireEvent.click(screen.getByRole("button", {name: "Keep document"}));
  const second = screen.getByRole("heading", {name: "Second policy"}).closest("article")!;
  fireEvent.click(within(second).getByText("More actions"));
  fireEvent.click(screen.getByRole("button", {name: "Remove document: Second policy"}));
  const dialog = screen.getByRole("dialog", {name: "Remove document?"});
  expect(dialog).toHaveTextContent("Second policy");
  expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.filter(call => call[2]?.method === "DELETE")).toHaveLength(1);
});

it("does not carry a failed review error into another knowledge gap", async () => {
  const questions = ["First question", "Second question"].map((question, index) => ({id: String(index), question, assistant: "No source available.", timestamp: "2026-11-10"}));
  vi.mocked(api).mockImplementation(async (path, _token, options) => {
    if (options?.method === "POST") throw new Error("First question could not be resolved.");
    return (path.includes("unanswered") ? {questions} : defaultResult(path)) as never;
  });
  wrap(<QualitySection metrics={metrics} onNavigate={vi.fn()}/>);
  fireEvent.click(screen.getByRole("button", {name: /Knowledge gaps/}));
  fireEvent.click(await screen.findByRole("button", {name: "Review knowledge gap: First question"}));
  fireEvent.click(screen.getByRole("button", {name: "Mark resolved"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("First question could not be resolved.");
  fireEvent.click(screen.getByRole("button", {name: "Close drawer"}));
  fireEvent.click(screen.getByRole("button", {name: "Review knowledge gap: Second question"}));
  const dialog = screen.getByRole("dialog", {name: "Knowledge gap"});
  expect(dialog).toHaveTextContent("Second question");
  expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
});

it("announces preview completion without applying settings or creating saved data", async () => {
  let resolvePreview!: (value: never) => void;
  vi.mocked(api).mockImplementation(async path => path.endsWith("/ai-settings/test")
    ? new Promise(resolve => { resolvePreview = resolve; }) : defaultResult(path) as never);
  renderAdmin("/knowledge?section=settings");
  fireEvent.click(await screen.findByRole("button", {name: "Run test"}));
  const status = within(screen.getByRole("main")).getByRole("status");
  await waitFor(() => expect(status).toHaveTextContent("Waiting for the preview answer"));
  await act(async () => resolvePreview({answer: "Synthetic preview answer.", sources: [], intent: "work", latency_ms: 1} as never));
  await waitFor(() => expect(status).toHaveTextContent("Preview ready. Review the response below."));
  expect(screen.getByRole("region", {name: "Preview response"})).toHaveTextContent("Synthetic preview answer.");
  const writes = vi.mocked(api).mock.calls.filter(call => call[2]?.method);
  expect(writes).toHaveLength(1);
  expect(writes[0][0]).toBe("/api/v1/admin/ai-settings/test");
});

it("shows missing rating and question samples instead of misleading zero percentages", () => {
  const emptyMetrics = {...metrics, questions: 0, grounded_answer_rate: 0, positive_feedback_rate: 0, feedback: 0, assistant_feedback: 0};
  const {rerender} = render(<OverviewSection metrics={emptyMetrics} loading={false} error={false} onRetry={vi.fn()} onNavigate={vi.fn()}/>);
  expect(screen.getByText("No ratings yet")).toBeInTheDocument();
  expect(screen.getByText("No questions yet")).toBeInTheDocument();
  expect(screen.queryByText("0%")).not.toBeInTheDocument();
  rerender(<OverviewSection metrics={{...emptyMetrics, questions: 2, feedback: 2}} loading={false} error={false} onRetry={vi.fn()} onNavigate={vi.fn()}/>);
  expect(screen.queryByText("No ratings yet")).not.toBeInTheDocument();
  expect(screen.getByText("2 recorded ratings")).toBeInTheDocument();
  expect(screen.getAllByText("0%")).toHaveLength(2);
});

it("combines document search and status filters and preserves them after viewing details", async () => {
  const documents = [
    {id:"ready", title:"Payroll handbook", name:"payroll.md", category:"HR", version:"2", index_status:"indexed"},
    {id:"error", title:"Payroll appendix", name:"appendix.md", category:"HR", version:"1", index_status:"error"},
    {id:"pending", title:"VPN guide", name:"vpn.md", category:"IT", version:"1", index_status:"pending"},
  ].map(item => ({...item, size:100, modified:"2026-11-10", chunk_count:3, indexed_at:null, index_error:null}));
  vi.mocked(api).mockImplementation(async path => (path === "/api/v1/documents" ? {documents} : defaultResult(path)) as never);
  wrap(<DocumentsSection/>);
  await screen.findByRole("heading", {name:"Payroll handbook"});
  fireEvent.change(screen.getByRole("textbox", {name:"Search documents"}), {target:{value:"PAYROLL"}});
  fireEvent.change(screen.getByRole("combobox", {name:"Document status"}), {target:{value:"indexed"}});
  expect(screen.getByRole("heading", {name:"Payroll handbook"})).toBeInTheDocument();
  expect(screen.queryByRole("heading", {name:"Payroll appendix"})).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", {name:"VPN guide"})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name:"Payroll handbook"}));
  const detail = screen.getByRole("dialog", {name:"Document details"});
  expect(detail).toHaveTextContent("payroll.md");
  expect(detail).toHaveTextContent("Searchable passages");
  fireEvent.click(within(detail).getByRole("button", {name:"Close drawer"}));
  expect(screen.getByRole("textbox", {name:"Search documents"})).toHaveValue("PAYROLL");
  expect(screen.getByRole("combobox", {name:"Document status"})).toHaveValue("indexed");
  fireEvent.change(screen.getByRole("combobox", {name:"Document status"}), {target:{value:"processing"}});
  expect(screen.getByText("No matching documents")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name:"Clear filters"}));
  expect(screen.getAllByRole("article")).toHaveLength(3);
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method)).toBe(false);
});

it("keeps populated positive feedback private and read-only", async () => {
  vi.mocked(api).mockImplementation(async path => path.includes("feedback") ? {feedback:[{id:"positive", sentiment:"positive", rating:5, question:"Payroll dates?", answer:"Twice a month.", comment:"Clear answer", created_at:"2026-11-10T09:00:00Z"}]} as never : defaultResult(path) as never);
  wrap(<QualitySection metrics={{...metrics, feedback:1, assistant_feedback:0}} onNavigate={vi.fn()}/>);
  fireEvent.click(screen.getByRole("button", {name:/^Helpful/}));
  fireEvent.click(await screen.findByRole("button", {name:"Review feedback: Payroll dates?"}));
  const detail = screen.getByRole("dialog", {name:"Response feedback"});
  expect(detail).toHaveTextContent("Account name hidden");
  expect(detail).toHaveTextContent("Clear answer");
  expect(within(detail).queryByRole("button", {name:"Mark resolved"})).not.toBeInTheDocument();
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method)).toBe(false);
});

it("resolves only the selected knowledge gap after an explicit action", async () => {
  let questions = [{id:"gap-a",question:"Equipment allowance?",assistant:"No reliable source.",timestamp:"2026-11-10"}];
  vi.mocked(api).mockImplementation(async (path, _token, options) => {
    if (options?.method === "POST") { questions = []; return {} as never; }
    return (path.includes("unanswered") ? {questions} : defaultResult(path)) as never;
  });
  wrap(<QualitySection metrics={metrics} onNavigate={vi.fn()}/>);
  fireEvent.click(screen.getByRole("button", {name:/Knowledge gaps/}));
  fireEvent.click(await screen.findByRole("button", {name:"Review knowledge gap: Equipment allowance?"}));
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method)).toBe(false);
  fireEvent.click(screen.getByRole("button", {name:"Mark resolved"}));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(await screen.findByText("No active knowledge gaps")).toBeInTheDocument();
  const writes = vi.mocked(api).mock.calls.filter(call => call[2]?.method);
  expect(writes).toHaveLength(1);
  expect(writes[0][0]).toBe("/api/v1/admin/quality/gap-a");
  expect(JSON.parse(String(writes[0][2]?.body))).toEqual({action:"resolved"});
});

it("closes document actions with Escape or when keyboard focus leaves the disclosure", async () => {
  const document = {id:"ready",title:"Keyboard policy",name:"keyboard.md",category:"HR",version:"1",index_status:"indexed",size:100,modified:"2026-11-10",chunk_count:3,indexed_at:null,index_error:null};
  vi.mocked(api).mockImplementation(async path => (path === "/api/v1/documents" ? {documents:[document]} : defaultResult(path)) as never);
  wrap(<DocumentsSection/>);
  const article = (await screen.findByRole("heading", {name:"Keyboard policy"})).closest("article")!;
  const summary = within(article).getByText("More actions").closest("summary")!;
  const disclosure = summary.closest("details")!;
  expect(summary).toHaveTextContent("for Keyboard policy");
  fireEvent.click(summary);
  expect(disclosure).toHaveAttribute("open");
  const detailsAction = within(article).getByRole("button", {name:"Document details: Keyboard policy"});
  detailsAction.focus();
  expect(disclosure).toHaveAttribute("open");
  fireEvent.keyDown(detailsAction, {key:"Escape"});
  expect(disclosure).not.toHaveAttribute("open");
  expect(summary).toHaveFocus();
  fireEvent.click(summary);
  detailsAction.focus();
  screen.getByRole("textbox", {name:"Search documents"}).focus();
  expect(disclosure).not.toHaveAttribute("open");
  expect(screen.getByRole("textbox", {name:"Search documents"})).toHaveFocus();
  expect(vi.mocked(api).mock.calls.some(call => call[2]?.method)).toBe(false);
});


