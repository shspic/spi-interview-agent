import { useCallback, useEffect, useMemo, useState } from "react";

import apiClient, { ensureCsrf, setUnauthorizedHandler } from "../api/client";
import { AuthContext } from "./authContext";

function AuthProvider({ children }) {
  const [currentUser, setCurrentUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  const clearAuth = useCallback(() => {
    setCurrentUser(null);
  }, []);

  useEffect(() => setUnauthorizedHandler(clearAuth), [clearAuth]);

  useEffect(() => {
    let active = true;
    const restoreSession = async () => {
      try {
        await ensureCsrf();
        const response = await apiClient.get("/api/auth/me");
        if (active) {
          setCurrentUser(response.data.user);
        }
      } catch {
        if (active) {
          clearAuth();
        }
      } finally {
        if (active) {
          setIsLoading(false);
        }
      }
    };
    restoreSession();
    return () => {
      active = false;
    };
  }, [clearAuth]);

  const login = useCallback(async ({ username, password }) => {
    await ensureCsrf();
    const response = await apiClient.post("/api/auth/login", { username, password });
    setCurrentUser(response.data.user);
    return response.data.user;
  }, []);

  const register = useCallback(
    async ({ username, password, inviteCode }) => {
      await ensureCsrf();
      await apiClient.post("/api/auth/register", {
        username,
        password,
        invite_code: inviteCode,
      });
      return login({ username, password });
    },
    [login],
  );

  const logout = useCallback(async () => {
    try {
      await apiClient.post("/api/auth/logout");
    } finally {
      clearAuth();
    }
  }, [clearAuth]);

  const logoutAll = useCallback(async () => {
    try {
      await apiClient.post("/api/auth/logout-all");
    } finally {
      clearAuth();
    }
  }, [clearAuth]);

  const refreshCurrentUser = useCallback(async () => {
    try {
      const response = await apiClient.get("/api/auth/me");
      setCurrentUser(response.data.user);
      return response.data.user;
    } catch (error) {
      clearAuth();
      throw error;
    }
  }, [clearAuth]);

  const value = useMemo(
    () => ({
      currentUser,
      isAuthenticated: Boolean(currentUser),
      isLoading,
      login,
      register,
      logout,
      logoutAll,
      refreshCurrentUser,
    }),
    [currentUser, isLoading, login, logout, logoutAll, refreshCurrentUser, register],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export default AuthProvider;
