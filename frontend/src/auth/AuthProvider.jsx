import { useCallback, useEffect, useMemo, useState } from "react";

import apiClient, {
  clearStoredToken,
  getStoredToken,
  saveStoredToken,
  setUnauthorizedHandler,
} from "../api/client";
import { AuthContext } from "./authContext";

function AuthProvider({ children }) {
  const [currentUser, setCurrentUser] = useState(null);
  const [token, setToken] = useState(() => getStoredToken());
  const [isLoading, setIsLoading] = useState(true);

  const clearAuth = useCallback(() => {
    clearStoredToken();
    setToken(null);
    setCurrentUser(null);
  }, []);

  useEffect(() => setUnauthorizedHandler(clearAuth), [clearAuth]);

  useEffect(() => {
    let active = true;

    const restoreSession = async () => {
      const storedToken = getStoredToken();

      if (!storedToken) {
        if (active) {
          setIsLoading(false);
        }
        return;
      }

      try {
        const response = await apiClient.get("/api/auth/me");

        if (active) {
          setToken(storedToken);
          setCurrentUser(response.data.user);
        }
      } catch {
        clearAuth();
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
    const response = await apiClient.post("/api/auth/login", {
      username,
      password,
    });
    const accessToken = response.data.access_token;

    saveStoredToken(accessToken);
    setToken(accessToken);
    setCurrentUser(response.data.user);

    return response.data.user;
  }, []);

  const register = useCallback(
    async ({ username, password, inviteCode }) => {
      await apiClient.post("/api/auth/register", {
        username,
        password,
        invite_code: inviteCode,
      });

      return login({ username, password });
    },
    [login],
  );

  const logout = useCallback(() => {
    clearAuth();
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
      token,
      isAuthenticated: Boolean(token && currentUser),
      isLoading,
      login,
      register,
      logout,
      refreshCurrentUser,
    }),
    [
      currentUser,
      isLoading,
      login,
      logout,
      refreshCurrentUser,
      register,
      token,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export default AuthProvider;
