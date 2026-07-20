import apiClient from "./client";

export async function getInterviewSessions(params = {}) {
  const response = await apiClient.get("/api/interview-sessions", { params });
  return response.data.sessions || [];
}

export async function getInterviewSession(sessionId) {
  const response = await apiClient.get(`/api/interview-sessions/${sessionId}`);
  return response.data;
}

export async function createInterviewSession(payload) {
  const response = await apiClient.post("/api/interview-sessions", payload);
  return response.data;
}

export async function cancelInterviewSession(sessionId) {
  const response = await apiClient.post(
    `/api/interview-sessions/${sessionId}/cancel`,
  );
  return response.data;
}

export async function deleteInterviewSession(sessionId) {
  const response = await apiClient.delete(
    `/api/interview-sessions/${sessionId}`,
  );
  return response.data;
}

export async function createRetrySession(sessionId) {
  const response = await apiClient.post(
    `/api/interview-sessions/${sessionId}/retry`,
  );
  return response.data;
}

export async function getInterviewComparison(sessionId) {
  const response = await apiClient.get(
    `/api/interview-sessions/${sessionId}/comparison`,
  );
  return response.data;
}

export async function getImprovementTasks(params = {}) {
  const response = await apiClient.get("/api/improvement-tasks", { params });
  return response.data.tasks || [];
}

export async function updateImprovementTask(taskId, status) {
  const response = await apiClient.patch(`/api/improvement-tasks/${taskId}`, {
    status,
  });
  return response.data;
}
