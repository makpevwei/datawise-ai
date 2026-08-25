import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
}));

const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

import Home from "../page";

describe("Home", () => {
  it("redirects to /login when not authenticated", () => {
    useAuthMock.mockReturnValue({ user: null, loading: false });
    render(<Home />);
    expect(replace).toHaveBeenCalledWith("/login");
  });

  it("redirects to /dashboard when authenticated", () => {
    useAuthMock.mockReturnValue({ user: { id: "1", full_name: "Test" }, loading: false });
    render(<Home />);
    expect(replace).toHaveBeenCalledWith("/dashboard");
  });

  it("does not redirect while auth state is still loading", () => {
    replace.mockClear();
    useAuthMock.mockReturnValue({ user: null, loading: true });
    render(<Home />);
    expect(replace).not.toHaveBeenCalled();
  });
});
