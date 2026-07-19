import apiClient from "./client";

export async function getMyProfile() {
  const response = await apiClient.get("/api/profile");
  return response.data;
}

export async function changeMyPassword(payload) {
  const response = await apiClient.post("/api/auth/change-password", payload);
  return response.data;
}

export async function previewMyDataCleanup() {
  const response = await apiClient.post("/api/account/data-cleanup-preview", {});
  return response.data;
}

export async function cleanupMyBusinessData(payload) {
  const response = await apiClient.post("/api/account/data-cleanup", payload);
  return response.data;
}
