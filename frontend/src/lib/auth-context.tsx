"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ApiError,
  getCurrentUser,
  getToken,
  loginUser,
  logoutUser,
  registerUser,
  setToken,
  type UserPublic,
} from "./api";

interface AuthContextValue {
  user: UserPublic | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, fullName: string) => Promise<void>;
  logout: () => Promise<void>;
  setUser: (user: UserPublic) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserPublic | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;
    const token = getToken();
    const verify = token
      ? getCurrentUser()
          .then((u) => {
            if (!cancelled) setUser(u);
          })
          .catch((err) => {
            if (cancelled) return;
            // Only a real "this token doesn't work" response should log the
            // user out -- a network blip or a cancelled request (e.g. React
            // Strict Mode's dev-only double-effect invocation aborting the
            // first fetch) must not silently wipe a valid token.
            if (err instanceof ApiError && err.status === 401) {
              setToken(null);
              setUser(null);
            }
          })
      : Promise.resolve();
    verify.finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const result = await loginUser({ email, password });
    setToken(result.access_token);
    setUser(result.user);
  }, []);

  const register = useCallback(async (email: string, password: string, fullName: string) => {
    const result = await registerUser({ email, password, full_name: fullName });
    setToken(result.access_token);
    setUser(result.user);
  }, []);

  const logout = useCallback(async () => {
    try {
      await logoutUser();
    } catch {
      // Stateless tokens: even if the network call fails, discarding the
      // local token still logs the user out of this browser.
    }
    setToken(null);
    setUser(null);
    router.push("/login");
  }, [router]);

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, setUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export { ApiError };
