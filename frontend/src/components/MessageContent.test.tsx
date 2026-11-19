import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { MessageContent } from "./MessageContent";

afterEach(cleanup);

it("renders saved answer emphasis, paragraphs and numbered questions as readable content", () => {
  const {container} = render(<MessageContent content={"**Maple-628:** Payroll is twice a month.\n\n1. Submit your request.\n2. Wait for your manager.\n\n- Check your balance.\n- Keep the confirmation."}/>);
  expect(screen.getByText("Maple-628:").tagName).toBe("STRONG");
  expect(container.querySelector("ol")?.children).toHaveLength(2);
  expect(container.querySelector("ul")?.children).toHaveLength(2);
  expect(container.textContent).not.toContain("**Maple-628:**");
});

it("never executes answer HTML or loads embedded images", () => {
  const {container} = render(<MessageContent content={'<script>alert("x")</script>\n\n<img src="https://example.com/tracker" onerror="alert(1)">\n\n![Private image](https://example.com/image.png)'}/>);
  expect(container.querySelector("script")).toBeNull();
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector("iframe")).toBeNull();
  expect(screen.getByText("Private image")).toBeInTheDocument();
});

it("keeps ordinary links accessible and rejects executable URL schemes", () => {
  render(<MessageContent content="[Policy](https://example.com/policy) [Unsafe](javascript:alert%281%29) [Payload](data:text/html,test)"/>);
  const safe = screen.getByRole("link", {name: "Policy"});
  expect(safe).toHaveAttribute("href", "https://example.com/policy");
  expect(safe).toHaveAttribute("rel", "noopener noreferrer");
  expect(screen.queryByRole("link", {name: "Unsafe"})).not.toBeInTheDocument();
  expect(screen.queryByRole("link", {name: "Payload"})).not.toBeInTheDocument();
});

it("contains wide Markdown tables in a keyboard accessible scroll region", () => {
  render(<MessageContent content={"| Category | Owner |\n| --- | --- |\n| Vacation | Manager |"}/>);
  expect(screen.getByRole("region", {name: "Response table"})).toHaveAttribute("tabindex", "0");
  expect(screen.getByRole("table")).toBeInTheDocument();
  expect(screen.getByRole("columnheader", {name: "Owner"})).toBeInTheDocument();
});

it("lets keyboard users focus a code sample to scroll long lines without losing content", () => {
  const code = "request_reference=" + "A".repeat(160);
  render(<MessageContent content={`\`\`\`text\n${code}\n\`\`\``}/>);
  const sample = screen.getByRole("region", {name: "Code sample"});
  expect(sample).toHaveAttribute("tabindex", "0");
  expect(sample).toHaveTextContent(code);
  sample.focus();
  expect(sample).toHaveFocus();
});
