/**
 * React context for session, configuration and platform-wide status.
 *
 * A single provider rather than three: the mock-data flag, the health readout
 * and the session all change together, and keeping them in separate contexts
 * would cause three re-renders where one suffices.
 */

"use client";

import * as React from "react";

import { api, getToken, setToken } from "@/lib/api";
import type { Health, User } from "@/types/api";

interface AppState {
  user: User | null;
  health: Health | null;
  /** True while the initial health and session load is in flight. */
  loading: boolean;
  /** True when any contributing dataset is synthetic development data. */
  isMock: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => void;
  refreshHealth: () => Promise<void>;
}

const AppContext = React.createContext<AppState | null>(null);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = React.useState<User | null>(null);
  const [health, setHealth] = React.useState<Health | null>(null);
  const [loading, setLoading] = React.useState(true);

  const refreshHealth = React.useCallback(async () => {
    try {
      const result = await api.health();
      setHealth(result);
    } catch {
      // A failed health check should degrade the indicators, not break the app.
      setHealth(null);
    }
  }, []);

  React.useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      const [healthResult] = await Promise.allSettled([refreshHealth()]);

      if (cancelled) return;

      if (getToken()) {
        try {
          const me = await api.me();
          if (!cancelled) {
            setUser({
              id: me.id,
              email: me.email,
              full_name: me.full_name,
              role: me.role,
              tenant_id: "",
            });
          }
        } catch {
          // Expired or invalid token: clear it so the UI shows the sign-in form
          // rather than silently making authenticated calls that will 401.
          setToken(null);
          if (!cancelled) setUser(null);
        }
      }

      if (!cancelled) setLoading(false);
    }

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [refreshHealth]);

  const signIn = React.useCallback(async (email: string, password: string) => {
    const result = await api.login(email, password);
    setUser(result.user);
    await refreshHealth();
  }, [refreshHealth]);

  const signOut = React.useCallback(() => {
    api.logout();
    setUser(null);
  }, []);

  const value = React.useMemo<AppState>(
    () => ({
      user,
      health,
      loading,
      isMock: health?.is_mock_data ?? false,
      signIn,
      signOut,
      refreshHealth,
    }),
    [user, health, loading, signIn, signOut, refreshHealth],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppState {
  const context = React.useContext(AppContext);
  if (!context) {
    throw new Error("useApp must be used inside an AppProvider");
  }
  return context;
}

/**
 * Data-fetching hook with abort handling and a manual refresh.
 *
 * Aborts in flight requests on dependency change, so rapidly moving a slider on
 * the what-if panel cannot deliver a stale response after a newer one.
 */
export function useApiData<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: React.DependencyList = [],
  options: { skip?: boolean } = {},
): {
  data: T | null;
  error: string | null;
  loading: boolean;
  refresh: () => void;
} {
  const [data, setData] = React.useState<T | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(!options.skip);
  const [nonce, setNonce] = React.useState(0);

  React.useEffect(() => {
    if (options.skip) {
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    let cancelled = false;

    setLoading(true);
    setError(null);

    fetcher(controller.signal)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if ((err as Error).name === "AbortError") return;
        setError(err instanceof Error ? err.message : "Request failed");
        setData(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce, options.skip]);

  const refresh = React.useCallback(() => setNonce((n) => n + 1), []);

  return { data, error, loading, refresh };
}
