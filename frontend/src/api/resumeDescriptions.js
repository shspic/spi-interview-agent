import apiClient from "./client";

export async function getResumeDescriptions() {
  const response = await apiClient.get("/api/resume-project-descriptions");
  return response.data.descriptions || [];
}

export async function getResumeDescription(descriptionId) {
  const response = await apiClient.get(
    `/api/resume-project-descriptions/${descriptionId}`,
  );
  return response.data;
}

export async function deleteResumeDescription(descriptionId) {
  const response = await apiClient.delete(
    `/api/resume-project-descriptions/${descriptionId}`,
  );
  return response.data;
}
