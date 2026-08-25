import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => "/dashboard",
}));

const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

import { AppShell } from "../AppShell";

describe("AppShell", () => {
  beforeEach(() => {
    replace.mockClear();
  });

  it("redirects to /login and renders nothing while unauthenticated", () => {
    useAuthMock.mockReturnValue({ user: null, loading: false, logout: vi.fn() });
    const { container } = render(
      <AppShell>
        <p>secret content</p>
      </AppShell>,
    );
    expect(replace).toHaveBeenCalledWith("/login");
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a loading spinner while auth state is resolving, without redirecting", () => {
    useAuthMock.mockReturnValue({ user: null, loading: true, logout: vi.fn() });
    render(
      <AppShell>
        <p>secret content</p>
      </AppShell>,
    );
    expect(replace).not.toHaveBeenCalled();
    expect(screen.queryByText("secret content")).not.toBeInTheDocument();
  });

  it("renders the persistent sidebar with all nav items and the page content when authenticated", () => {
    useAuthMock.mockReturnValue({
      user: { id: "1", full_name: "Ada Lovelace", email: "ada@example.com" },
      loading: false,
      logout: vi.fn(),
    });
    render(
      <AppShell>
        <p>secret content</p>
      </AppShell>,
    );

    for (const label of ["Dashboard", "Ask DataWise", "My Data", "Analyses", "Reports", "Insights"]) {
      expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByText("secret content")).toBeInTheDocument();
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
  });
});
