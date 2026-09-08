type PyWebviewApi = {
  minimize_window: () => Promise<void>;
  toggle_maximize_window: () => Promise<{ maximized: boolean }>;
  close_window: () => Promise<void>;
  get_model_groups: () => Promise<ModelGroup[]>;
  get_current_model: () => Promise<ModelSelection | null>;
  set_current_model: (site: string, model: string) => Promise<void>;
};

export type ModelGroup = {
  name: string;
  models: ModelConfig[];
};

export type ModelConfig = {
  name: string;
  image_vision: boolean;
};

export type ModelSelection = {
  site: string;
  model: string;
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

export async function getModelGroups(): Promise<ModelGroup[]> {
  if (!window.pywebview?.api) {
    if (window.location.protocol !== "file:") {
      return [];
    }

    await new Promise<void>((resolve) => {
      window.addEventListener("pywebviewready", () => resolve(), { once: true });
    });
  }

  return (await window.pywebview?.api.get_model_groups()) ?? [];
}

export async function getCurrentModel(): Promise<ModelSelection | null> {
  return (await window.pywebview?.api.get_current_model()) ?? null;
}

export async function setCurrentModel(site: string, model: string): Promise<void> {
  await window.pywebview?.api.set_current_model(site, model);
}
