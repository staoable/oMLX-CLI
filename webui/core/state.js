export const DEFAULT_MODEL = "Qwen3.5-35B-A3B-8bit";
export const SIDEBAR_STORAGE_KEY = "eyuai-cli-sidebar-collapsed";
export const ARCHIVED_SESSIONS_KEY = "omlxcli-show-archived-sessions";

export const state = {
  sessions: [],
  currentVendorId: null,
  /** 最近一次 loadSession 时服务端返回的 api_base */
  sessionApiBaseFromServer: "",
  /** 当前设置里用于展示的 base：与当前所选模型设置一致 */
  effectiveApiBase: "",
  includeArchivedSessions:
    typeof localStorage !== "undefined" &&
    localStorage.getItem(ARCHIVED_SESSIONS_KEY) === "1",
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
