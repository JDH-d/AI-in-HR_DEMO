import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useVisualViewport } from "./useVisualViewport";

class Viewport extends EventTarget {
  height = 800;
  offsetTop = 0;
  scale = 1;
}
let viewport: Viewport;
let nextFrame: FrameRequestCallback | undefined;
let nextId = 0;
const height = () => document.documentElement.style.getPropertyValue("--visible-viewport-height");
const top = () => document.documentElement.style.getPropertyValue("--visible-viewport-top");
function Harness() { useVisualViewport(); return <input aria-label="Message"/>; }
function flush() { act(() => { const callback = nextFrame; nextFrame = undefined; callback?.(0); }); }

beforeEach(() => {
  viewport = new Viewport();
  nextFrame = undefined;
  vi.stubGlobal("visualViewport", viewport);
  vi.stubGlobal("requestAnimationFrame", vi.fn((callback: FrameRequestCallback) => { nextFrame = callback; return ++nextId; }));
  vi.stubGlobal("cancelAnimationFrame", vi.fn(() => { nextFrame = undefined; }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("tracks visual-only shrink and pan while the layout viewport stays unchanged", () => {
  vi.stubGlobal("innerHeight", 800);
  render(<Harness/>);
  expect(height()).toBe("800px");
  expect(document.documentElement.dataset.viewportShort).toBe("false");
  act(() => { viewport.height = 360; viewport.offsetTop = 120; viewport.dispatchEvent(new Event("resize")); });
  flush();
  expect(window.innerHeight).toBe(800);
  expect(height()).toBe("360px");
  expect(top()).toBe("120px");
  expect(document.documentElement.dataset.viewportShort).toBe("true");
  act(() => { viewport.offsetTop = 160; viewport.dispatchEvent(new Event("scroll")); });
  flush();
  expect(top()).toBe("160px");
  act(() => { viewport.height = 800; viewport.offsetTop = 0; viewport.dispatchEvent(new Event("resize")); });
  flush();
  expect(height()).toBe("800px");
  expect(top()).toBe("0px");
  expect(document.documentElement.dataset.viewportShort).toBe("false");
});

it("handles content-resizing browsers and window-only fallbacks", () => {
  vi.stubGlobal("visualViewport", undefined);
  vi.stubGlobal("innerHeight", 800);
  render(<Harness/>);
  expect(height()).toBe("800px");
  act(() => { vi.stubGlobal("innerHeight", 400); window.dispatchEvent(new Event("resize")); });
  flush();
  expect(height()).toBe("400px");
  expect(top()).toBe("0px");
  expect(document.documentElement.dataset.viewportShort).toBe("true");
});

it("does not fight pinch zoom or accept transient invalid geometry", () => {
  render(<Harness/>);
  act(() => { viewport.height = 300; viewport.offsetTop = 90; viewport.scale = 2; viewport.dispatchEvent(new Event("resize")); });
  flush();
  expect(height()).toBe("800px");
  expect(top()).toBe("0px");
  expect(document.documentElement.dataset.viewportShort).toBe("false");
  act(() => { viewport.height = 0; viewport.scale = 1; viewport.dispatchEvent(new Event("resize")); });
  flush();
  expect(height()).toBe("800px");
  act(() => { viewport.height = 600; viewport.offsetTop = -10; viewport.dispatchEvent(new Event("resize")); });
  flush();
  expect(height()).toBe("600px");
  expect(top()).toBe("0px");
});

it("coalesces viewport events and removes pending work and global state on unmount", () => {
  const { unmount } = render(<Harness/>);
  act(() => {
    viewport.dispatchEvent(new Event("resize"));
    viewport.dispatchEvent(new Event("scroll"));
    window.dispatchEvent(new Event("resize"));
  });
  expect(requestAnimationFrame).toHaveBeenCalledTimes(1);
  unmount();
  expect(cancelAnimationFrame).toHaveBeenCalledTimes(1);
  expect(height()).toBe("");
  expect(top()).toBe("");
  expect(document.documentElement.dataset.viewportShort).toBeUndefined();
  act(() => { viewport.dispatchEvent(new Event("resize")); window.dispatchEvent(new Event("resize")); });
  expect(requestAnimationFrame).toHaveBeenCalledTimes(1);
});
