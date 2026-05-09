export const DEFAULT_MODEL = "Qwen3.5-35B-A3B-8bit";
export const SIDEBAR_STORAGE_KEY = "eyuai-cli-sidebar-collapsed";
export const ARCHIVED_SESSIONS_KEY = "omlxcli-show-archived-sessions";
/** 入门向导「稍后」后不再自动弹出，直至用户从空状态手动打开。 */
export const ONBOARDING_DISMISSED_KEY = "omlxcli-onboarding-dismissed";

export const state = {
  sessions: [],
  /** `/api/vendors` 条数；用于空状态与向导逻辑。 */
  vendorCount: 0,
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
  activeStreamController: null,
  sendingSessionId: null,
  currentSessionObservability: {
    executions: [],
    contextInjections: [],
  },
};

export function el(id) {
  return document.getElementById(id);
}
