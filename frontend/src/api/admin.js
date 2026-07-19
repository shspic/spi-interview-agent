import apiClient from "./client";

function compactParams(params = {}) {
  return Object.fromEntries(
    Object.entries(params).filter(
      ([, value]) => value !== "" && value !== null && value !== undefined,
    ),
  );
}

export async function getAdminUsers(params) {
  const response = await apiClient.get("/api/admin/users", {
    params: compactParams(params),
  });
  return response.data;
}

export async function getAdminUser(userId) {
  const response = await apiClient.get(`/api/admin/users/${userId}`);
  return response.data;
}

export async function updateAdminUserStatus(userId, isActive) {
  const response = await apiClient.patch(`/api/admin/users/${userId}/status`, {
    is_active: isActive,
  });
  return response.data;
}

export async function resetAdminUserPassword(userId, newPassword) {
  const response = await apiClient.post(
    `/api/admin/users/${userId}/reset-password`,
    { new_password: newPassword },
  );
  return response.data;
}

export async function deleteAdminUser(userId, confirmUsername) {
  const response = await apiClient.delete(`/api/admin/users/${userId}`, {
    data: { confirm_username: confirmUsername },
  });
  return response.data;
}

export async function getAdminUsageSummary(params) {
  const response = await apiClient.get("/api/admin/usage/summary", {
    params: compactParams(params),
  });
  return response.data;
}

export async function getAdminUserUsage(userId, params) {
  const response = await apiClient.get(`/api/admin/usage/users/${userId}`, {
    params: compactParams(params),
  });
  return response.data;
}

export async function getAdminAgentRuns(params) {
  const response = await apiClient.get("/api/admin/agent-runs", {
    params: compactParams(params),
  });
  return response.data;
}

export async function getAdminAuditLogs(params) {
  const response = await apiClient.get("/api/admin/audit-logs", {
    params: compactParams(params),
  });
  return response.data;
}

export async function getRegistrationSettings() {
  const response = await apiClient.get("/api/admin/settings/registration");
  return response.data;
}

export async function updateRegistrationInviteCode(inviteCode) {
  const response = await apiClient.put(
    "/api/admin/settings/registration/invite-code",
    { invite_code: inviteCode },
  );
  return response.data;
}

export async function previewAdminCleanup() {
  const response = await apiClient.post(
    "/api/admin/maintenance/cleanup-preview",
  );
  return response.data;
}

export async function runAdminCleanup(confirm) {
  const response = await apiClient.post("/api/admin/maintenance/cleanup", {
    confirm,
  });
  return response.data;
}
