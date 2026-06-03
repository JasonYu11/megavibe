import { describe, expect, it } from "vitest";
import {
  DEFAULT_LAYOUT,
  MIN_MAIN_COMPACT,
  MIN_MAIN_DESKTOP,
  computeWorkbenchLayout,
  clampLayout,
  layoutColumns,
  parseLayout,
} from "./layoutState";

describe("workbench layout state", () => {
  it("falls back for missing or invalid persisted layout", () => {
    expect(parseLayout(null)).toEqual(DEFAULT_LAYOUT);
    expect(parseLayout("{nope")).toEqual(DEFAULT_LAYOUT);
  });

  it("clamps persisted column widths", () => {
    expect(clampLayout({ leftWidth: 120, rightWidth: 900 })).toMatchObject({
      leftWidth: 220,
      rightWidth: 560,
    });
    expect(clampLayout({ leftWidth: 390, rightWidth: 120 })).toMatchObject({
      leftWidth: 360,
      rightWidth: 300,
    });
  });

  it("preserves collapsed state and maps it to grid columns", () => {
    const layout = parseLayout(JSON.stringify({ leftWidth: 300, rightWidth: 420, leftCollapsed: true }));
    expect(layout.leftCollapsed).toBe(true);
    expect(layout.rightCollapsed).toBe(false);
    expect(layoutColumns(layout)).toBe("0px minmax(460px, 1fr) 420px");
  });

  it("computes stable five-column desktop layout", () => {
    const computed = computeWorkbenchLayout({ layout: DEFAULT_LAYOUT, containerWidth: 1440 });
    expect(computed.columns).toBe("284px 8px minmax(620px, 1fr) 8px 372px");
    expect(computed.mainMinWidth).toBe(MIN_MAIN_DESKTOP);
    expect(computed.leftVisible).toBe(true);
    expect(computed.rightVisible).toBe(true);
  });

  it("keeps the main workspace above compact minimum by shrinking the right dock", () => {
    const computed = computeWorkbenchLayout({ layout: DEFAULT_LAYOUT, containerWidth: 1180 });
    expect(computed.mainMinWidth).toBe(MIN_MAIN_COMPACT);
    expect(computed.leftVisible).toBe(true);
    expect(computed.rightVisible).toBe(true);
    expect(computed.rightWidth).toBeLessThanOrEqual(DEFAULT_LAYOUT.rightWidth);
    expect(computed.leftWidth + computed.leftHandleWidth + computed.mainMinWidth + computed.rightHandleWidth + computed.rightWidth).toBeLessThanOrEqual(1180);
  });

  it("auto-hides the right dock before violating the main minimum", () => {
    const computed = computeWorkbenchLayout({ layout: DEFAULT_LAYOUT, containerWidth: 900 });
    expect(computed.leftVisible).toBe(true);
    expect(computed.rightVisible).toBe(false);
    expect(computed.mainMinWidth).toBe(MIN_MAIN_COMPACT);
  });

  it("supports left then right drag calculations without losing a handle on roomy screens", () => {
    const afterLeftDrag = clampLayout({ ...DEFAULT_LAYOUT, leftWidth: DEFAULT_LAYOUT.leftWidth + 60 });
    const leftComputed = computeWorkbenchLayout({ layout: afterLeftDrag, containerWidth: 1440 });
    expect(leftComputed.leftVisible).toBe(true);
    expect(leftComputed.rightVisible).toBe(true);
    expect(leftComputed.rightHandleWidth).toBe(8);

    const afterRightDrag = clampLayout({ ...afterLeftDrag, rightWidth: afterLeftDrag.rightWidth + 80 });
    const rightComputed = computeWorkbenchLayout({ layout: afterRightDrag, containerWidth: 1440 });
    expect(rightComputed.leftVisible).toBe(true);
    expect(rightComputed.rightVisible).toBe(true);
    expect(rightComputed.rightWidth).toBeGreaterThan(leftComputed.rightWidth);
  });
});
