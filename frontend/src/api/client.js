import axios from "axios";

const TOKEN_STORAGE_KEY = "spi_interview_access_token";
let unauthorizedHandler = null;

export function getStoredToken() {
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function saveStoredToken(token) {
  localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearStoredToken() {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
}

export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = handler;

  return () => {
    if (unauthorizedHandler === handler) {
      unauthorizedHandler = null;
    }
  };
}

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000",
  timeout: 120000,
});

apiClient.interceptors.request.use((config) => {
  const token = getStoredToken();

  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }

  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const disabledAccount =
      error.response?.status === 403 && error.response?.data?.detail === "账号已停用";

    if (error.response?.status === 401 || disabledAccount) {
      clearStoredToken();
      unauthorizedHandler?.();
    }

    return Promise.reject(error);
  },
);

export default apiClient;
