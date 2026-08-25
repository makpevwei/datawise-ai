import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const setUser = vi.fn();
const baseUser = {
  id: "u1",
  email: "ada@example.com",
  full_name: "Ada Lovelace",
  is_active: true,
  currency: "USD" as const,
  decimal_places: 2,
  created_at: new Date().toISOString(),
};

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ user: baseUser, loading: false, login: vi.fn(), register: vi.fn(), logout: vi.fn(), setUser }),
}));

import * as api from "@/lib/api";
import SettingsPage from "../page";

describe("SettingsPage", () => {
  it("shows the authenticated user's profile", () => {
    render(<SettingsPage />);
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
  });

  it("saves updated currency and decimal places, and calls setUser with the response", async () => {
    const updateSpy = vi.spyOn(api, "updateUserSettings").mockResolvedValue({
      ...baseUser,
      currency: "NGN",
      decimal_places: 0,
    });

    render(<SettingsPage />);

    fireEvent.change(screen.getByLabelText(/currency/i), { target: { value: "NGN" } });
    fireEvent.change(screen.getByLabelText(/decimal places/i), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: /save settings/i }));

    await waitFor(() =>
      expect(updateSpy).toHaveBeenCalledWith({ currency: "NGN", decimal_places: 0 }),
    );
    await waitFor(() => expect(setUser).toHaveBeenCalledWith(expect.objectContaining({ currency: "NGN" })));
    expect(await screen.findByText(/settings saved/i)).toBeInTheDocument();
  });

  it("disables Save until a setting actually changes", () => {
    render(<SettingsPage />);
    expect(screen.getByRole("button", { name: /save settings/i })).toBeDisabled();
  });
});
