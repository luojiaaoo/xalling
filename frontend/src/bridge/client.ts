type PyWebviewApi = {
  minimize_window: () => Promise<void>;
  toggle_maximize_window: () => Promise<{ maximized: boolean }>;
  close_window: () => Promise<void>;
};

declare global {
  interface Window {
    pywebview?: { api: PyWebviewApi };
  }
}

export async function minimizeWindow(): Promise<void> {
  await window.pywebview?.api.minimize_window();
}

export async function toggleMaximizeWindow(): Promise<boolean> {
  const result = await window.pywebview?.api.toggle_maximize_window();
  return result?.maximized ?? false;
}

export async function closeWindow(): Promise<void> {
  await window.pywebview?.api.close_window();
}
