import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const routerReplace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: routerReplace, push: vi.fn() }),
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    user: { id: "u1", full_name: "Ada Lovelace", email: "ada@example.com", currency: "USD", decimal_places: 2 },
    loading: false,
    logout: vi.fn(),
    setUser: vi.fn(),
  }),
}));

import { AskDataWise } from "../AskDataWise";
import * as api from "@/lib/api";
import type { AgentAnswer, DatasetSummary } from "@/lib/types";

const dataset: DatasetSummary = {
  id: "d1",
  name: "orders.csv",
  source_file: "orders.csv",
  sheet_name: null,
  kind: "uploaded",
  row_count: 20,
  column_count: 5,
  quality_rating: "good",
  created_at: new Date().toISOString(),
};

function baseAnswer(overrides: Partial<AgentAnswer> = {}): AgentAnswer {
  return {
    question: "What were total sales?",
    session_id: "s1",
    configured: true,
    executive_summary: "Total sales were 4,100.",
    key_findings: [
      {
        text: "Total sales were 4,100.",
        label: "CALCULATED",
        verification_note: null,
        citations: [],
      },
    ],
    risks: [],
    recommendations: [],
    claim_comparisons: [],
    charts: [],
    citations: [],
    trace: [
      { stage: "understanding_question", label: "Understanding question", detail: "What were total sales?" },
      { stage: "analysis", label: "✓ calculate_metric(...)", detail: "sum(amount) = 4100" },
    ],
    tool_invocations: [
      { id: "t1", tool_name: "calculate_metric", input: { dataset_id: "d1" }, output_summary: "4100", succeeded: true, duration_ms: 12 },
    ],
    raw_answer_text: null,
    error: null,
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("AskDataWise", () => {
  it("shows a not-configured message when the backend has no LLM key", async () => {
    vi.spyOn(api, "getAgentStatus").mockResolvedValue({ configured: false });
    render(<AskDataWise datasets={[dataset]} />);
    await waitFor(() => expect(screen.getByText(/ai features are not configured/i)).toBeInTheDocument());
  });

  it("populates the input from a suggestion chip without auto-submitting, and Clear resets it", async () => {
    vi.spyOn(api, "getAgentStatus").mockResolvedValue({ configured: true });
    const askSpy = vi.spyOn(api, "askAgent").mockResolvedValue(baseAnswer());

    render(<AskDataWise datasets={[dataset]} />);
    await screen.findByRole("button", { name: /total number of records/i });

    fireEvent.click(screen.getByRole("button", { name: /total number of records/i }));

    const textarea = screen.getByPlaceholderText(/ask anything about your data/i) as HTMLTextAreaElement;
    expect(textarea.value).toMatch(/total number of records/i);
    expect(askSpy).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /^clear$/i }));
    expect(textarea.value).toBe("");
    expect(askSpy).not.toHaveBeenCalled();
  });

  it("New Chat clears the conversation even when it never had a URL session id", async () => {
    // Regression test: a brand-new conversation only gets a sessionId in
    // React state from askAgent's response -- the URL never carried
    // ?session= in the first place, so New Chat must reset state directly
    // rather than relying on a route-change remount to do it.
    vi.spyOn(api, "getAgentStatus").mockResolvedValue({ configured: true });
    vi.spyOn(api, "askAgent").mockResolvedValue(baseAnswer());

    render(<AskDataWise datasets={[dataset]} />);
    const textarea = screen.getByPlaceholderText(/ask anything about your data/i);
    fireEvent.change(textarea, { target: { value: "What were total sales?" } });
    fireEvent.click(screen.getByRole("button", { name: /analyze/i }));

    await waitFor(() => expect(screen.getAllByText("Total sales were 4,100.").length).toBeGreaterThan(0));

    fireEvent.click(screen.getByRole("button", { name: /new chat/i }));

    expect(screen.queryByText("Total sales were 4,100.")).not.toBeInTheDocument();
    expect(routerReplace).toHaveBeenCalledWith("/ask");
  });

  it("syncs the session id to the URL after answering, so a remount can restore the conversation", async () => {
    // Regression test: navigating away from /ask and back (e.g. via the
    // sidebar nav link) unmounts this component. The URL is the only thing
    // that survives that -- so the session id must be pushed there after
    // the first answer, and a fresh mount with that id in initialSessionId
    // must restore the conversation via getSession() rather than showing
    // an empty workspace as if nothing had ever been asked.
    vi.spyOn(api, "getAgentStatus").mockResolvedValue({ configured: true });
    vi.spyOn(api, "askAgent").mockResolvedValue(baseAnswer({ session_id: "s-persisted" }));

    const { unmount } = render(<AskDataWise datasets={[dataset]} />);
    const textarea = screen.getByPlaceholderText(/ask anything about your data/i);
    fireEvent.change(textarea, { target: { value: "What were total sales?" } });
    fireEvent.click(screen.getByRole("button", { name: /analyze/i }));

    await waitFor(() => expect(screen.getAllByText("Total sales were 4,100.").length).toBeGreaterThan(0));
    expect(routerReplace).toHaveBeenCalledWith("/ask?session=s-persisted", { scroll: false });

    // Simulate the remount a real navigation-away-and-back would cause,
    // now with the URL-synced session id passed back in as a prop.
    unmount();
    vi.spyOn(api, "getSession").mockResolvedValue({
      id: "s-persisted",
      title: "What were total sales?",
      status: "active",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      last_activity_at: new Date().toISOString(),
      message_count: 1,
      messages: [
        {
          id: "m1",
          role: "assistant",
          kind: "agent_answer",
          content: "",
          metadata: baseAnswer({ session_id: "s-persisted" }) as unknown as Record<string, unknown>,
          created_at: new Date().toISOString(),
        },
      ],
    });

    render(<AskDataWise datasets={[dataset]} initialSessionId="s-persisted" />);
    await waitFor(() => expect(screen.getAllByText("Total sales were 4,100.").length).toBeGreaterThan(0));
  });

  it("submits a question and renders the structured answer", async () => {
    vi.spyOn(api, "getAgentStatus").mockResolvedValue({ configured: true });
    vi.spyOn(api, "askAgent").mockResolvedValue(baseAnswer());

    render(<AskDataWise datasets={[dataset]} />);

    const textarea = screen.getByPlaceholderText(/ask anything about your data/i);
    fireEvent.change(textarea, { target: { value: "What were total sales?" } });
    fireEvent.click(screen.getByRole("button", { name: /analyze/i }));

    await waitFor(() => expect(screen.getAllByText("Total sales were 4,100.").length).toBeGreaterThan(0));
    expect(screen.getByText("CALCULATED")).toBeInTheDocument();
  });

  it("reveals the agent trace when toggled", async () => {
    vi.spyOn(api, "getAgentStatus").mockResolvedValue({ configured: true });
    vi.spyOn(api, "askAgent").mockResolvedValue(baseAnswer());

    render(<AskDataWise datasets={[dataset]} />);
    fireEvent.click(screen.getByRole("button", { name: /total number of records/i }));
    fireEvent.click(screen.getByRole("button", { name: /analyze/i }));

    const toggle = await screen.findByRole("button", { name: /show how datawise worked/i });
    fireEvent.click(toggle);

    expect(screen.getByText(/calculate_metric/)).toBeInTheDocument();
  });

  it("shows citations for document-grounded findings", async () => {
    vi.spyOn(api, "getAgentStatus").mockResolvedValue({ configured: true });
    vi.spyOn(api, "askAgent").mockResolvedValue(
      baseAnswer({
        key_findings: [
          {
            text: "Management cites a supply disruption.",
            label: "DOCUMENT_EVIDENCE",
            verification_note: null,
            citations: [
              {
                document_id: "doc1",
                document_name: "management_report.pdf",
                chunk_id: "c1",
                location: { page: 2 },
                excerpt: "Management attributes the decline to a supply disruption.",
                relevance_score: 0.9,
              },
            ],
          },
        ],
        citations: [
          {
            document_id: "doc1",
            document_name: "management_report.pdf",
            chunk_id: "c1",
            location: { page: 2 },
            excerpt: "Management attributes the decline to a supply disruption.",
            relevance_score: 0.9,
          },
        ],
      }),
    );

    render(<AskDataWise datasets={[dataset]} />);
    fireEvent.click(screen.getByRole("button", { name: /total number of records/i }));
    fireEvent.click(screen.getByRole("button", { name: /analyze/i }));

    await waitFor(() => expect(screen.getByText("DOCUMENT EVIDENCE")).toBeInTheDocument());
    expect(screen.getByText(/management_report\.pdf/)).toBeInTheDocument();
  });

  it("separates data-grounded recommendations from general/web-knowledge ones", async () => {
    // Real gap fixed: previously both rendered in one flat list,
    // distinguished only by a small per-item badge -- easy to miss while
    // skimming which recommendation actually came from this data.
    vi.spyOn(api, "getAgentStatus").mockResolvedValue({ configured: true });
    vi.spyOn(api, "askAgent").mockResolvedValue(
      baseAnswer({
        recommendations: [
          {
            text: "Investigate the Lagos region's outsized contribution to growth.",
            label: "CALCULATED",
            verification_note: null,
            citations: [],
          },
          {
            text: "Regularly reviewing pricing strategy is a common practice.",
            label: "VERIFIED_FROM_WEB",
            verification_note: null,
            citations: [],
          },
        ],
      }),
    );

    render(<AskDataWise datasets={[dataset]} />);
    fireEvent.click(screen.getByRole("button", { name: /total number of records/i }));
    fireEvent.click(screen.getByRole("button", { name: /analyze/i }));

    await waitFor(() => expect(screen.getByText(/Lagos region/)).toBeInTheDocument());
    expect(screen.getByText("Recommended Areas to Investigate")).toBeInTheDocument();
    expect(screen.getByText("What Usually Works")).toBeInTheDocument();
    expect(screen.getByText(/From outside sources, not from your data/)).toBeInTheDocument();
    expect(screen.getByText(/Regularly reviewing pricing strategy/)).toBeInTheDocument();
  });

  it("shows only the grounded recommendations section when nothing is web-sourced", async () => {
    vi.spyOn(api, "getAgentStatus").mockResolvedValue({ configured: true });
    vi.spyOn(api, "askAgent").mockResolvedValue(
      baseAnswer({
        recommendations: [
          { text: "Look into the Q2 dip in the West region.", label: "CALCULATED", verification_note: null, citations: [] },
        ],
      }),
    );

    render(<AskDataWise datasets={[dataset]} />);
    fireEvent.click(screen.getByRole("button", { name: /total number of records/i }));
    fireEvent.click(screen.getByRole("button", { name: /analyze/i }));

    await waitFor(() => expect(screen.getByText(/Q2 dip/)).toBeInTheDocument());
    expect(screen.queryByText("What Usually Works")).not.toBeInTheDocument();
  });

  it("shows an error banner when the request fails", async () => {
    vi.spyOn(api, "getAgentStatus").mockResolvedValue({ configured: true });
    vi.spyOn(api, "askAgent").mockRejectedValue(new Error("network exploded"));

    render(<AskDataWise datasets={[dataset]} />);
    fireEvent.click(screen.getByRole("button", { name: /total number of records/i }));
    fireEvent.click(screen.getByRole("button", { name: /analyze/i }));

    await waitFor(() => expect(screen.getByText(/network exploded/i)).toBeInTheDocument());
  });

  it("renders an agent-level error inside the answer card", async () => {
    vi.spyOn(api, "getAgentStatus").mockResolvedValue({ configured: true });
    vi.spyOn(api, "askAgent").mockResolvedValue(
      baseAnswer({ configured: false, error: "AI features are not configured.", executive_summary: null, key_findings: [] }),
    );

    render(<AskDataWise datasets={[dataset]} />);
    fireEvent.click(screen.getByRole("button", { name: /total number of records/i }));
    fireEvent.click(screen.getByRole("button", { name: /analyze/i }));

    await waitFor(() => expect(screen.getAllByText(/ai features are not configured/i).length).toBeGreaterThan(0));
  });
});
