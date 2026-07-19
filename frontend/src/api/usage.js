import apiClient from "./client";

export async function getMyUsage() {
  const response = await apiClient.get("/api/usage/me");
  return response.data;
}
