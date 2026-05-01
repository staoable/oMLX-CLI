export const DEFAULT_MODEL = "Qwen3.5-35B-A3B-8bit";
export const SIDEBAR_STORAGE_KEY = "eyuai-cli-sidebar-collapsed";

export const state = {
  sessions: [],
  currentSessionId: null,
  assistantBuffer: "",
  streamingMdEl: null,
  streamingStepsEl: null,
  sending: false,
  pendingAttachments: [],
  pendingConfirm: null,
  currentSessionObservability: {
    executions: [],
    contextInjections: [],
  },
};

export function el(id) {
  return document.getElementById(id);
}
