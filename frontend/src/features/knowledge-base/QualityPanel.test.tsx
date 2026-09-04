import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QualityPanel } from "./QualityPanel";

vi.mock("@tanstack/react-query", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-query")>();
  return {
    ...actual,
    useQuery: () => ({
      data: undefined,
      isLoading: false,
      isError: true,
      refetch: vi.fn(),
    }),
  };
});
vi.mock("../../app/providers", () => ({
  useAuth: () => ({ token: "demo-token" }),
}));

describe("QualityPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows a retrieval error instead of a false empty queue", () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <QualityPanel onAddSource={() => undefined} />
      </QueryClientProvider>,
    );

    expect(screen.getByText("Unable to load quality signals")).toBeInTheDocument();
    expect(screen.queryByText("No answers need review")).not.toBeInTheDocument();
  });
});
