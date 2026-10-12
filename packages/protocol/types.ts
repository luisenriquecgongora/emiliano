/**
 * @emiliano/protocol - Shared TypeScript Types & Event Contracts
 */

export type HarnessType =
  | 'auto'
  | 'direct'
  | 'claude_code'
  | 'antigravity'
  | 'opencode'
  | 'codex'
  | 'cowork'
  | 'mcp';

export type TaskStatus = 'pending' | 'running' | 'waiting_approval' | 'completed' | 'failed' | 'paused';

export interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface UIElementTarget {
  id?: string;
  name: string;
  role?: string;
  bounds: BoundingBox;
  confidence?: number;
  action: 'click' | 'double_click' | 'right_click' | 'type' | 'hover' | 'scroll';
}

export interface DAGStep {
  id: string;
  title: string;
  description?: string;
  status: TaskStatus;
  assignedHarness: HarnessType;
  dependencies: string[];
  output?: string;
  error?: string;
}

export interface TaskDefinition {
  id: string;
  goal: string;
  harnessPreference: HarnessType;
  modelConfig?: {
    provider?: string;
    modelName?: string;
    temperature?: number;
    fallbackChain?: string[];
  };
  steps: DAGStep[];
  currentStepId?: string;
  status: TaskStatus;
  createdAt: string;
  updatedAt: string;
}

// WebSocket Event Payloads
export type ClientMessageType =
  | 'TASK_START'
  | 'TASK_PAUSE'
  | 'TASK_RESUME'
  | 'TASK_CANCEL'
  | 'APPROVAL_RESPONSE'
  | 'HARNESS_SWITCH'
  | 'PING';

export type ServerMessageType =
  | 'PONG'
  | 'TASK_STATE'
  | 'DAG_UPDATE'
  | 'HUD_HIGHLIGHT'
  | 'HUD_CLEAR'
  | 'THOUGHT_STREAM'
  | 'APPROVAL_REQUEST'
  | 'HARNESS_LOG'
  | 'ERROR';

export interface TaskStartMessage {
  type: 'TASK_START';
  payload: {
    taskId?: string;
    goal: string;
    harnessPreference?: HarnessType;
    localModel?: string;
    remoteModel?: string;
  };
}

export interface ApprovalResponseMessage {
  type: 'APPROVAL_RESPONSE';
  payload: {
    requestId: string;
    approved: boolean;
    feedback?: string;
  };
}

export interface HUDHighlightMessage {
  type: 'HUD_HIGHLIGHT';
  payload: {
    element: UIElementTarget;
    reasoning: string;
    durationMs?: number;
  };
}

export interface ThoughtStreamMessage {
  type: 'THOUGHT_STREAM';
  payload: {
    stepId?: string;
    chunk: string;
    harness: HarnessType;
  };
}

export interface ApprovalRequestMessage {
  type: 'APPROVAL_REQUEST';
  payload: {
    requestId: string;
    title: string;
    description: string;
    dangerous: boolean;
    actionType: string;
  };
}

export interface HarnessLogMessage {
  type: 'HARNESS_LOG';
  payload: {
    harness: HarnessType;
    stream: 'stdout' | 'stderr' | 'system';
    text: string;
  };
}
