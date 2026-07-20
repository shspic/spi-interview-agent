import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const CSRF_COOKIE_NAME = import.meta.env.VITE_AUTH_CSRF_COOKIE_NAME || "spi_csrf";
const SAFE_METHODS = new Set(["get", "head", "options"]);
const AUTH_ENDPOINTS = new Set([
  "/api/auth/csrf",
  "/api/auth/login",
  "/api/auth/register",
  "/api/auth/refresh",
  "/api/auth/logout",
]);
const CSRF_RETRYABLE_AUTH_ENDPOINTS = new Set([
  "/api/auth/login",
  "/api/auth/register",
  "/api/auth/logout",
  "/api/auth/logout-all",
]);

let unauthorizedHandler = null;
let refreshPromise = null;

function readCookie(name) {
  const prefix = `${encodeURIComponent(name)}=`;
  const item = document.cookie
    .split(";")
    .map((value) => value.trim())
    .find((value) => value.startsWith(prefix));
  return item ? decodeURIComponent(item.slice(prefix.length)) : null;
}

export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = handler;
  return () => {
    if (unauthorizedHandler === handler) {
      unauthorizedHandler = null;
    }
  };
}

const authClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000,
  withCredentials: true,
});

export async function ensureCsrf() {
  if (!readCookie(CSRF_COOKIE_NAME)) {
    await authClient.get("/api/auth/csrf");
  }
  return readCookie(CSRF_COOKIE_NAME);
}

async function refreshSession() {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      const csrfToken = await ensureCsrf();
      try {
        await authClient.post(
          "/api/auth/refresh",
          {},
          { headers: { "X-CSRF-Token": csrfToken } },
        );
      } catch (error) {
        const errorCode = error.response?.data?.error_code;
        if (
          error.response?.status !== 403 ||
          (errorCode !== "csrf_required" && errorCode !== "csrf_invalid")
        ) {
          throw error;
        }
        await authClient.get("/api/auth/csrf");
        const renewedToken = readCookie(CSRF_COOKIE_NAME);
        await authClient.post(
          "/api/auth/refresh",
          {},
          { headers: { "X-CSRF-Token": renewedToken } },
        );
      }
    })()
      .catch((error) => {
        unauthorizedHandler?.();
        throw error;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000,
  withCredentials: true,
});

apiClient.interceptors.request.use(async (config) => {
  const method = (config.method || "get").toLowerCase();
  if (!SAFE_METHODS.has(method)) {
    const csrfToken = await ensureCsrf();
    config.headers["X-CSRF-Token"] = csrfToken;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const config = error.config || {};
    const method = (config.method || "get").toLowerCase();
    const endpoint = new URL(config.url || "", API_BASE_URL).pathname;
    const errorCode = error.response?.data?.error_code;
    const csrfError =
      error.response?.status === 403 &&
      (errorCode === "csrf_required" || errorCode === "csrf_invalid");

    if (
      csrfError &&
      !config._csrfRetried &&
      (!AUTH_ENDPOINTS.has(endpoint) || CSRF_RETRYABLE_AUTH_ENDPOINTS.has(endpoint))
    ) {
      config._csrfRetried = true;
      await authClient.get("/api/auth/csrf");
      if (SAFE_METHODS.has(method) || CSRF_RETRYABLE_AUTH_ENDPOINTS.has(endpoint)) {
        return apiClient.request(config);
      }
    }

    if (
      error.response?.status === 401 &&
      !config._refreshRetried &&
      !AUTH_ENDPOINTS.has(endpoint)
    ) {
      config._refreshRetried = true;
      await refreshSession();
      if (SAFE_METHODS.has(method)) {
        return apiClient.request(config);
      }
    }

    if (errorCode === "account_disabled") {
      unauthorizedHandler?.();
    }
    return Promise.reject(error);
  },
);

export default apiClient;
