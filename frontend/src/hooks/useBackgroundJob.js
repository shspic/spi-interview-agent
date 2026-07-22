import { useCallback, useEffect, useRef, useState } from "react";

import apiClient from "../api/client";

const TERMINAL_STATUSES = new Set([
  "succeeded",
  "failed",
  "cancelled",
  "timed_out",
]);
const STORAGE_PREFIX = "spi.background-job.";
const MAX_POLLS = 1800;

function createIdempotencyKey(prefix) {
  const randomPart = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  return `${prefix}:${randomPart}`;
}

export default function useBackgroundJob(storageKey, onSucceeded, onUnsuccessfulTerminal) {
  const [job, setJob] = useState(null);
  const timerRef = useRef(null);
  const pollRef = useRef(null);
  const pollCountRef = useRef(0);
  const mountedRef = useRef(true);
  const successHandlerRef = useRef(onSucceeded);
  const unsuccessfulTerminalHandlerRef = useRef(onUnsuccessfulTerminal);
  const handledTerminalTaskIdsRef = useRef(new Set());

  const storageName = `${STORAGE_PREFIX}${storageKey}`;

  const stopPolling = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const poll = useCallback(
    async (taskId) => {
      stopPolling();
      if (!mountedRef.current || pollCountRef.current >= MAX_POLLS) {
        return;
      }
      pollCountRef.current += 1;
      try {
        const response = await apiClient.get(`/api/tasks/${taskId}`);
        if (!mountedRef.current) {
          return;
        }
        const nextJob = response.data;
        setJob(nextJob);
        if (TERMINAL_STATUSES.has(nextJob.status)) {
          window.localStorage.removeItem(storageName);
          if (!handledTerminalTaskIdsRef.current.has(taskId)) {
            handledTerminalTaskIdsRef.current.add(taskId);
            try {
              if (nextJob.status === "succeeded") {
                await successHandlerRef.current?.(nextJob.result || {});
              } else {
                await unsuccessfulTerminalHandlerRef.current?.(nextJob);
              }
            } catch (handlerError) {
              console.error("background job terminal handler failed:", handlerError);
            }
          }
          return;
        }
        timerRef.current = window.setTimeout(() => pollRef.current?.(taskId), 1000);
      } catch (error) {
        if (!mountedRef.current) {
          return;
        }
        if (error.response?.status === 404) {
          window.localStorage.removeItem(storageName);
          return;
        }
        timerRef.current = window.setTimeout(() => pollRef.current?.(taskId), 2000);
      }
    },
    [storageName, stopPolling],
  );

  useEffect(() => {
    successHandlerRef.current = onSucceeded;
    unsuccessfulTerminalHandlerRef.current = onUnsuccessfulTerminal;
    pollRef.current = poll;
  }, [onSucceeded, onUnsuccessfulTerminal, poll]);

  const createJob = useCallback(
    async (path, payload, idempotencyPrefix) => {
      const response = await apiClient.post(path, payload, {
        headers: { "Idempotency-Key": createIdempotencyKey(idempotencyPrefix) },
      });
      const nextJob = response.data;
      setJob(nextJob);
      pollCountRef.current = 0;
      window.localStorage.setItem(storageName, nextJob.task_id);
      void poll(nextJob.task_id);
      return nextJob;
    },
    [poll, storageName],
  );

  const cancelJob = useCallback(async () => {
    if (!job?.task_id || TERMINAL_STATUSES.has(job.status)) {
      return;
    }
    const response = await apiClient.post(`/api/tasks/${job.task_id}/cancel`);
    setJob(response.data);
    if (TERMINAL_STATUSES.has(response.data.status)) {
      stopPolling();
      window.localStorage.removeItem(storageName);
    }
  }, [job, stopPolling, storageName]);

  useEffect(() => {
    mountedRef.current = true;
    const taskId = window.localStorage.getItem(storageName);
    if (taskId) {
      pollCountRef.current = 0;
      timerRef.current = window.setTimeout(() => pollRef.current?.(taskId), 0);
    }
    return () => {
      mountedRef.current = false;
      stopPolling();
    };
  }, [poll, storageName, stopPolling]);

  return {
    job,
    createJob,
    cancelJob,
    isRunning: Boolean(job && !TERMINAL_STATUSES.has(job.status)),
  };
}
