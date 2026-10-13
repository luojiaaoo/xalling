import { useSyncExternalStore } from "react";

import App from "./App";
import { getShutdownState, subscribeShutdown } from "./api/client";
import { ShutdownScreen } from "./components/ShutdownScreen";

export function ApplicationRoot() {
  const shutdown = useSyncExternalStore(subscribeShutdown, getShutdownState);
  return shutdown.phase === "idle" || shutdown.phase === "closing"
    ? <App />
    : <ShutdownScreen state={shutdown} />;
}
