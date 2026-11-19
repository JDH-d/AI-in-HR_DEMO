import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ReplyTemplates } from "./ReplyTemplates";

afterEach(cleanup);

it("appends the chosen suggestion without replacing existing notes or inserting it on selection", () => {
  const onInsert = vi.fn();
  render(<ReplyTemplates action="request_information" value="Keep these facts." disabled={false} onInsert={onInsert}/>);
  fireEvent.click(screen.getByText("Response templates", { selector: "summary" }));
  fireEvent.change(screen.getByLabelText("Choose a response template"), { target: { value: "supporting-information" } });
  expect(onInsert).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Append template" }));
  expect(onInsert).toHaveBeenCalledOnce();
  expect(onInsert.mock.calls[0][0]).toMatch(/^Keep these facts\.\n\nPlease provide \[\[relevant supporting information\]\]/);
});

it("does not append beyond the explanation limit or discard any existing text", () => {
  const onInsert = vi.fn();
  render(<ReplyTemplates action="complete" value={"A".repeat(9990)} disabled={false} onInsert={onInsert}/>);
  fireEvent.click(screen.getByText("Response templates", { selector: "summary" }));
  expect(screen.getByRole("button", { name: "Append template" })).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent("your existing text is kept");
  fireEvent.click(screen.getByRole("button", { name: "Append template" }));
  expect(onInsert).not.toHaveBeenCalled();
});
