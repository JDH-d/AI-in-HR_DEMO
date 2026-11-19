import { useEffect } from "react";

// Safari can shrink and pan only the visual viewport when its keyboard opens.
// CSS viewport units and height media queries still describe the larger layout
// viewport in that case. Publish the visible bounds without disabling zoom or
// trying to infer whether a keyboard, browser chrome, or split screen caused it.
export function useVisualViewport() {
  useEffect(() => {
    const root = document.documentElement;
    const viewport = window.visualViewport;
    let frame = 0;
    const update = () => {
      frame = 0;
      // Let pinch zoom pan naturally; resizing the layout to the magnified
      // viewport would fight the user's zoom and make content jump.
      if (viewport && Math.abs(viewport.scale - 1) > 0.01) return;
      const height = viewport?.height ?? window.innerHeight;
      const top = viewport?.offsetTop ?? 0;
      if (!Number.isFinite(height) || height <= 0 || !Number.isFinite(top)) return;
      root.style.setProperty("--visible-viewport-height", `${height}px`);
      root.style.setProperty("--visible-viewport-top", `${Math.max(0, top)}px`);
      root.dataset.viewportShort = String(height <= 540);
    };
    const schedule = () => {
      if (!frame) frame = window.requestAnimationFrame(update);
    };
    update();
    viewport?.addEventListener("resize", schedule);
    viewport?.addEventListener("scroll", schedule);
    window.addEventListener("resize", schedule);
    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      viewport?.removeEventListener("resize", schedule);
      viewport?.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      root.style.removeProperty("--visible-viewport-height");
      root.style.removeProperty("--visible-viewport-top");
      delete root.dataset.viewportShort;
    };
  }, []);
}
