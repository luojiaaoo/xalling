type PyWebviewApi = {
  minimize_window: () => Promise<void>;
  toggle_maximize_window: () => Promise<{ maximized: boolean }>;
  close_window: () => Promise<void>;
  get_model_groups: () => Promise<ModelGroup[]>;
  get_model_sites: () => Promise<ModelSite[]>;
  save_model_site: (
    originalName: string | null,
    name: string,
    apiUrl: string,
    apiKey: string,
    models: ModelConfig[],
  ) => Promise<void>;
  delete_model_site: (name: string) => Promise<void>;
  get_current_model: () => Promise<ModelSelection | null>;
  set_current_model: (site: string, model: string) => Promise<void>;
  get_current_theme: () => Promise<string>;
  set_current_theme: (name: string) => Promise<void>;
};

export type ModelGroup = {
  name: string;
  models: ModelConfig[];
};

export type ModelConfig = {
  name: string;
  image_vision: boolean;
};

export type ModelSite = {
  name: string;
  api_url: string;
  api_key: string;
  models: ModelConfig[];
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

async function getBridgeApi(): Promise<PyWebviewApi | undefined> {
  if (window.pywebview?.api) {
    return window.pywebview.api;
  }

  if (window.location.protocol === "file:") {
    await new Promise<void>((resolve) => {
      window.addEventListener("pywebviewready", () => resolve(), { once: true });
    });
  }

  return window.pywebview?.api;
}

export async function getModelGroups(): Promise<ModelGroup[]> {
  const api = await getBridgeApi();
  return (await api?.get_model_groups()) ?? [];
}

export async function getModelSites(): Promise<ModelSite[]> {
  const api = await getBridgeApi();
  return (await api?.get_model_sites()) ?? [];
}

export async function saveModelSite(
  originalName: string | null,
  name: string,
  apiUrl: string,
  apiKey: string,
  models: ModelConfig[],
): Promise<void> {
  const api = await getBridgeApi();
  if (!api) {
    throw new Error("桌面应用桥接尚未准备好");
  }
  await api.save_model_site(originalName, name, apiUrl, apiKey, models);
}

export async function deleteModelSite(name: string): Promise<void> {
  const api = await getBridgeApi();
  if (!api) {
    throw new Error("桌面应用桥接尚未准备好");
  }
  await api.delete_model_site(name);
}

export async function getCurrentModel(): Promise<ModelSelection | null> {
  const api = await getBridgeApi();
  return (await api?.get_current_model()) ?? null;
}

export async function setCurrentModel(site: string, model: string): Promise<void> {
  const api = await getBridgeApi();
  await api?.set_current_model(site, model);
}

export async function getCurrentTheme(): Promise<string> {
  const api = await getBridgeApi();
  return (await api?.get_current_theme()) ?? "default";
}

export async function setCurrentTheme(name: string): Promise<void> {
  const api = await getBridgeApi();
  if (!api) {
    throw new Error("桌面应用桥接尚未准备好");
  }
  await api.set_current_theme(name);
}
