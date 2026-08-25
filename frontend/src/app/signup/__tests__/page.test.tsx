import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
}));

const register = vi.fn();
vi.mock("@/lib/auth-context", async () => {
  const actual = await vi.importActual<typeof import("@/lib/auth-context")>("@/lib/auth-context");
  return {
    ...actual,
    useAuth: () => ({ login: vi.fn(), register, logout: vi.fn(), user: null, loading: false }),
  };
});

import { ApiError } from "@/lib/api";
import SignupPage from "../page";

function fillForm({
  fullName = "Ada Lovelace",
  email = "ada@example.com",
  password = "correct horse battery",
  confirmPassword = "correct horse battery",
}: Partial<Record<"fullName" | "email" | "password" | "confirmPassword", string>> = {}) {
  fireEvent.change(screen.getByLabelText(/full name/i), { target: { value: fullName } });
  fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: email } });
  fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: password } });
  fireEvent.change(screen.getByLabelText(/confirm password/i), { target: { value: confirmPassword } });
}

describe("SignupPage", () => {
  it("renders all required fields", () => {
    render(<SignupPage />);
    expect(screen.getByLabelText(/full name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^password$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/confirm password/i)).toBeInTheDocument();
  });

  it("rejects mismatched passwords before calling the API", async () => {
    render(<SignupPage />);
    fillForm({ confirmPassword: "a different password" });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    expect(await screen.findByText(/passwords do not match/i)).toBeInTheDocument();
    expect(register).not.toHaveBeenCalled();
  });

  it("rejects a password shorter than 8 characters before calling the API", async () => {
    render(<SignupPage />);
    fillForm({ password: "short", confirmPassword: "short" });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    expect(await screen.findByText(/at least 8 characters/i)).toBeInTheDocument();
    expect(register).not.toHaveBeenCalled();
  });

  it("registers and redirects to the dashboard on success", async () => {
    register.mockResolvedValue(undefined);
    render(<SignupPage />);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() =>
      expect(register).toHaveBeenCalledWith("ada@example.com", "correct horse battery", "Ada Lovelace"),
    );
    await waitFor(() => expect(push).toHaveBeenCalledWith("/dashboard"));
  });

  it("shows a useful error message when registration fails", async () => {
    register.mockRejectedValue(new ApiError("An account with this email already exists.", 409));
    render(<SignupPage />);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    expect(await screen.findByText(/already exists/i)).toBeInTheDocument();
  });
});
