import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { SourceEvidence } from "./SourceEvidence";

afterEach(cleanup);
it("groups repeated document excerpts without losing distinct evidence or interpreting HTML",()=>{
  const base={source:"policy.md", title:"Company policy", version:"1",category:"HR",score:1,section:"Eligibility",excerpt:"**Applies to:** everyone. <script>not executable</script>"};
  render(<SourceEvidence sources={[base,base,{...base,section:"Steps",excerpt:"Ask your manager."}]}/>);
  expect(screen.getByText(/Sources · 1/)).toBeInTheDocument();
  expect(screen.getAllByText("Eligibility")).toHaveLength(1);
  expect(screen.getByText("Ask your manager.")).toBeInTheDocument();
  expect(document.querySelector("script")).toBeNull();
  expect(screen.getByText(/Applies to: everyone/)).toBeInTheDocument();
  // One source needs just one disclosure; opening Sources reveals its evidence.
  expect(screen.getByText("Company policy").closest("details")).toHaveAttribute("open");
});
