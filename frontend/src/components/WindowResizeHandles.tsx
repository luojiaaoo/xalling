import { useRef, type PointerEvent } from "react";

import { resizeWindow } from "../bridge/client";

const MIN_WIDTH = 400;
const MIN_HEIGHT = 600;
const EDGES = ["n", "s", "w", "e", "nw", "ne", "sw", "se"] as const;

type ResizeEdge = (typeof EDGES)[number];

type ResizeState = {
  edge: ResizeEdge;
  pointerId: number;
  startX: number;
  startY: number;
  startWidth: number;
  startHeight: number;
};

type ResizeRequest = {
  edge: ResizeEdge;
  width: number;
  height: number;
};

export function WindowResizeHandles({ disabled = false }: { disabled?: boolean }) {
  const resizeState = useRef<ResizeState | null>(null);
  const animationFrame = useRef<number | null>(null);
  const pendingResize = useRef<ResizeRequest | null>(null);
  const resizeInFlight = useRef(false);

  function scheduleResize() {
    if (animationFrame.current !== null || resizeInFlight.current) {
      return;
    }

    animationFrame.current = requestAnimationFrame(() => {
      animationFrame.current = null;
      const request = pendingResize.current;
      if (!request) {
        return;
      }

      pendingResize.current = null;
      resizeInFlight.current = true;
      void resizeWindow(request.width, request.height, request.edge).finally(() => {
        resizeInFlight.current = false;
        if (pendingResize.current) {
          scheduleResize();
        }
      });
    });
  }

  function handlePointerDown(event: PointerEvent<HTMLDivElement>, edge: ResizeEdge) {
    if (disabled || event.button !== 0) {
      return;
    }

    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    resizeState.current = {
      edge,
      pointerId: event.pointerId,
      startX: event.screenX,
      startY: event.screenY,
      startWidth: window.innerWidth,
      startHeight: window.innerHeight,
    };
  }

  function handlePointerMove(event: PointerEvent<HTMLDivElement>) {
    const state = resizeState.current;
    if (!state || state.pointerId !== event.pointerId) {
      return;
    }

    const deltaX = event.screenX - state.startX;
    const deltaY = event.screenY - state.startY;
    const nextWidth = state.edge.includes("e")
      ? state.startWidth + deltaX
      : state.edge.includes("w")
        ? state.startWidth - deltaX
        : state.startWidth;
    const nextHeight = state.edge.includes("s")
      ? state.startHeight + deltaY
      : state.edge.includes("n")
        ? state.startHeight - deltaY
        : state.startHeight;
    const width = Math.max(MIN_WIDTH, Math.round(nextWidth));
    const height = Math.max(MIN_HEIGHT, Math.round(nextHeight));

    pendingResize.current = { width, height, edge: state.edge };
    scheduleResize();
  }

  function handlePointerUp(event: PointerEvent<HTMLDivElement>) {
    if (resizeState.current?.pointerId !== event.pointerId) {
      return;
    }

    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    resizeState.current = null;
  }

  if (disabled) {
    return null;
  }

  return (
    <div className="window-resize-handles" aria-hidden="true">
      {EDGES.map((edge) => (
        <div
          key={edge}
          className={`window-resize-handle window-resize-${edge}`}
          onPointerDown={(event) => handlePointerDown(event, edge)}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
        />
      ))}
    </div>
  );
}
