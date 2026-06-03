export interface WorkbenchLayout {
  leftWidth: number;
  rightWidth: number;
  leftCollapsed: boolean;
  rightCollapsed: boolean;
}

export interface ComputedWorkbenchLayout {
  leftWidth: number;
  mainWidth: number;
  mainMinWidth: number;
  rightWidth: number;
  leftVisible: boolean;
  rightVisible: boolean;
  leftHandleWidth: number;
  rightHandleWidth: number;
  columns: string;
}

export const DEFAULT_LAYOUT: WorkbenchLayout = {
  leftWidth: 284,
  rightWidth: 372,
  leftCollapsed: false,
  rightCollapsed: false,
};

export const LAYOUT_STORAGE_KEY = "mcode.workbench.layout.v1";

export const MIN_LEFT = 220;
export const MAX_LEFT = 360;
export const MIN_RIGHT = 300;
export const MAX_RIGHT = 560;
export const MIN_MAIN_DESKTOP = 620;
export const MIN_MAIN_COMPACT = 520;
export const MIN_MAIN_FLOOR = 360;
export const RESIZE_HANDLE_WIDTH = 8;

export function clampLayout(value: Partial<WorkbenchLayout> = {}): WorkbenchLayout {
  return {
    leftWidth: clampNumber(value.leftWidth, MIN_LEFT, MAX_LEFT, DEFAULT_LAYOUT.leftWidth),
    rightWidth: clampNumber(value.rightWidth, MIN_RIGHT, MAX_RIGHT, DEFAULT_LAYOUT.rightWidth),
    leftCollapsed: Boolean(value.leftCollapsed),
    rightCollapsed: Boolean(value.rightCollapsed),
  };
}

export function parseLayout(raw: string | null): WorkbenchLayout {
  if (!raw) return DEFAULT_LAYOUT;
  try {
    const value = JSON.parse(raw) as Partial<WorkbenchLayout>;
    return clampLayout(value);
  } catch {
    return DEFAULT_LAYOUT;
  }
}

export function layoutColumns(layout: WorkbenchLayout): string {
  const left = layout.leftCollapsed ? "0px" : `${layout.leftWidth}px`;
  const right = layout.rightCollapsed ? "0px" : `${layout.rightWidth}px`;
  return `${left} minmax(460px, 1fr) ${right}`;
}

export function computeWorkbenchLayout({
  layout,
  containerWidth,
}: {
  layout: WorkbenchLayout;
  containerWidth: number;
}): ComputedWorkbenchLayout {
  const safeWidth = Number.isFinite(containerWidth) && containerWidth > 0 ? containerWidth : 1440;
  const targetMain = safeWidth < 1280 ? MIN_MAIN_COMPACT : MIN_MAIN_DESKTOP;
  const applied = clampLayout(layout);

  let leftVisible = !applied.leftCollapsed;
  let rightVisible = !applied.rightCollapsed;
  let leftWidth = leftVisible ? applied.leftWidth : 0;
  let rightWidth = rightVisible ? applied.rightWidth : 0;
  let leftHandleWidth = leftVisible ? RESIZE_HANDLE_WIDTH : 0;
  let rightHandleWidth = rightVisible ? RESIZE_HANDLE_WIDTH : 0;

  const fits = () => leftWidth + leftHandleWidth + targetMain + rightHandleWidth + rightWidth <= safeWidth;

  if (!fits() && rightVisible) {
    const remainingRight = safeWidth - leftWidth - leftHandleWidth - rightHandleWidth - targetMain;
    if (remainingRight >= MIN_RIGHT) {
      rightWidth = Math.min(rightWidth, remainingRight);
    } else {
      rightVisible = false;
      rightWidth = 0;
      rightHandleWidth = 0;
    }
  }

  if (!fits() && leftVisible) {
    const remainingLeft = safeWidth - rightWidth - rightHandleWidth - leftHandleWidth - targetMain;
    if (remainingLeft >= MIN_LEFT) {
      leftWidth = Math.min(leftWidth, remainingLeft);
    } else {
      leftVisible = false;
      leftWidth = 0;
      leftHandleWidth = 0;
    }
  }

  const sideWidth = leftWidth + leftHandleWidth + rightHandleWidth + rightWidth;
  const mainWidth = Math.max(MIN_MAIN_FLOOR, safeWidth - sideWidth);
  const mainMinWidth = Math.max(MIN_MAIN_FLOOR, Math.min(targetMain, safeWidth - sideWidth));
  const columns = [
    `${leftWidth}px`,
    `${leftHandleWidth}px`,
    `minmax(${mainMinWidth}px, 1fr)`,
    `${rightHandleWidth}px`,
    `${rightWidth}px`,
  ].join(" ");

  return {
    leftWidth,
    mainWidth,
    mainMinWidth,
    rightWidth,
    leftVisible,
    rightVisible,
    leftHandleWidth,
    rightHandleWidth,
    columns,
  };
}

function clampNumber(value: unknown, min: number, max: number, fallback: number): number {
  const numberValue = typeof value === "number" && Number.isFinite(value) ? value : fallback;
  return Math.max(min, Math.min(max, Math.round(numberValue)));
}
