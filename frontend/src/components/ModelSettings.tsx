import {
  CheckCircleFilled,
  CloudDownloadOutlined,
  CloudServerOutlined,
  DeleteOutlined,
  LoadingOutlined,
  PictureOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import {
  Button,
  Checkbox,
  Empty,
  Input,
  Modal,
  Popconfirm,
  Radio,
  Select,
  Switch,
  Tooltip,
} from "antd";
import { useEffect, useState } from "react";

import {
  deleteModelSite,
  fetchModelNames,
  getModelSites,
  saveModelSite,
  type ApiProtocol,
  type ModelConfig,
  type ModelSite,
} from "../bridge/client";

type ProviderDraft = {
  originalName: string | null;
  name: string;
  apiUrl: string;
  apiKey: string;
  apiProtocol: ApiProtocol;
  models: ModelDraft[];
};

type ModelDraft = ModelConfig & {
  draftId: string;
};

function newModel(name = ""): ModelDraft {
  return {
    draftId: crypto.randomUUID(),
    name,
    image_vision: false,
    max_context_tokens: null,
  };
}

function newDraft(): ProviderDraft {
  return {
    originalName: null,
    name: "",
    apiUrl: "",
    apiKey: "",
    apiProtocol: "anthropic",
    models: [],
  };
}

function draftFromSite(site: ModelSite): ProviderDraft {
  return {
    originalName: site.name,
    name: site.name,
    apiUrl: site.api_url,
    apiKey: site.api_key,
    apiProtocol: site.api_protocol,
    models: site.models.map((model) => ({
      ...model,
      draftId: crypto.randomUUID(),
    })),
  };
}

function formatBridgeError(error: unknown): string {
  return error instanceof Error ? error.message : "保存失败，请稍后重试。";
}

type ModelSettingsProps = {
  onModelsChanged: () => void;
  section: string;
};

export function ModelSettings({ onModelsChanged, section }: ModelSettingsProps) {
  const [sites, setSites] = useState<ModelSite[]>([]);
  const [draft, setDraft] = useState<ProviderDraft>(newDraft);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [fetchingModels, setFetchingModels] = useState(false);
  const [modelPickerOpen, setModelPickerOpen] = useState(false);
  const [remoteModelNames, setRemoteModelNames] = useState<string[]>([]);
  const [selectedRemoteNames, setSelectedRemoteNames] = useState<string[]>([]);
  const [modelSearch, setModelSearch] = useState("");
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function reload(preferredName?: string | null) {
    setLoading(true);
    setError(null);
    try {
      const nextSites = await getModelSites();
      const nextSelected = nextSites.find(
        (site) => site.name === (preferredName ?? selectedName),
      ) ?? nextSites[0];
      setSites(nextSites);
      if (nextSelected) {
        setSelectedName(nextSelected.name);
        setDraft(draftFromSite(nextSelected));
      } else {
        setSelectedName(null);
        setDraft(newDraft());
      }
    } catch (loadError) {
      setError(formatBridgeError(loadError));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void reload(null);
  }, []);

  function selectSite(site: ModelSite) {
    setSelectedName(site.name);
    setDraft(draftFromSite(site));
    setFeedback(null);
    setError(null);
  }

  function addProvider() {
    setSelectedName(null);
    setDraft(newDraft());
    setFeedback(null);
    setError(null);
  }

  function updateModel(index: number, changes: Partial<ModelConfig>) {
    setDraft((current) => ({
      ...current,
      models: current.models.map((model, modelIndex) =>
        modelIndex === index ? { ...model, ...changes } : model,
      ),
    }));
  }

  function removeModel(index: number) {
    setDraft((current) => ({
      ...current,
      models: current.models.filter((_, modelIndex) => modelIndex !== index),
    }));
  }

  async function fetchModels() {
    if (!draft.apiUrl.trim()) {
      setError("请填写 API 地址。");
      return;
    }
    if (!draft.apiKey.trim()) {
      setError("请填写 API Key。");
      return;
    }

    setFetchingModels(true);
    setFeedback(null);
    setError(null);
    try {
      const names = await fetchModelNames(draft.apiUrl.trim(), draft.apiKey);
      setRemoteModelNames(names);
      setSelectedRemoteNames([]);
      setModelSearch("");
      setModelPickerOpen(true);
      setFeedback(`已获取 ${names.length} 个模型，请选择需要添加的模型。`);
    } catch (fetchError) {
      setError(formatBridgeError(fetchError));
    } finally {
      setFetchingModels(false);
    }
  }

  function addSelectedModels() {
    const existingNames = new Set(
      draft.models.map((model) => model.name.trim()).filter(Boolean),
    );
    const namesToAdd = selectedRemoteNames.filter((name) => !existingNames.has(name));
    setDraft((current) => ({
      ...current,
      models: [
        ...current.models,
        ...namesToAdd.map((name) => newModel(name)),
      ],
    }));
    setModelPickerOpen(false);
    setFeedback(`已添加 ${namesToAdd.length} 个模型，请保存配置。`);
  }

  function validateDraft(): string | null {
    if (!draft.name.trim()) {
      return "请填写供应商名称。";
    }
    if (!draft.apiKey.trim()) {
      return "请填写 API Key。";
    }
    const names = draft.models.map((model) => model.name.trim());
    if (names.some((name) => !name)) {
      return "请填写每个模型的名称。";
    }
    if (new Set(names).size !== names.length) {
      return "同一供应商内的模型名称不能重复。";
    }
    return null;
  }

  async function save() {
    const validationError = validateDraft();
    if (validationError) {
      setError(validationError);
      return;
    }

    setSaving(true);
    setFeedback(null);
    setError(null);
    try {
      const nextName = draft.name.trim();
      await saveModelSite(
        draft.originalName,
        nextName,
        draft.apiUrl.trim(),
        draft.apiKey,
        draft.models.map((model) => ({
          name: model.name.trim(),
          image_vision: model.image_vision,
          max_context_tokens: model.max_context_tokens,
        })),
        draft.apiProtocol,
      );
      await reload(nextName);
      onModelsChanged();
      setFeedback("模型配置已保存。");
    } catch (saveError) {
      setError(formatBridgeError(saveError));
    } finally {
      setSaving(false);
    }
  }

  async function removeProvider() {
    if (!draft.originalName) {
      addProvider();
      return;
    }

    setSaving(true);
    setFeedback(null);
    setError(null);
    try {
      await deleteModelSite(draft.originalName);
      await reload(null);
      onModelsChanged();
      setFeedback("供应商已删除。");
    } catch (deleteError) {
      setError(formatBridgeError(deleteError));
    } finally {
      setSaving(false);
    }
  }

  const isNew = draft.originalName === null;
  const existingModelNames = new Set(
    draft.models.map((model) => model.name.trim()).filter(Boolean),
  );
  const normalizedModelSearch = modelSearch.trim().toLocaleLowerCase();
  const filteredRemoteNames = remoteModelNames.filter((name) => (
    !normalizedModelSearch || name.toLocaleLowerCase().includes(normalizedModelSearch)
  ));
  const selectableFilteredNames = filteredRemoteNames.filter(
    (name) => !existingModelNames.has(name),
  );
  const allFilteredSelected = selectableFilteredNames.length > 0
    && selectableFilteredNames.every((name) => selectedRemoteNames.includes(name));
  const someFilteredSelected = selectableFilteredNames.some(
    (name) => selectedRemoteNames.includes(name),
  );

  function selectFilteredModels(checked: boolean) {
    if (!checked) {
      const visibleNames = new Set(selectableFilteredNames);
      setSelectedRemoteNames((current) => current.filter((name) => !visibleNames.has(name)));
      return;
    }
    setSelectedRemoteNames((current) => [
      ...new Set([...current, ...selectableFilteredNames]),
    ]);
  }

  function selectRemoteModel(name: string, checked: boolean) {
    setSelectedRemoteNames((current) => {
      if (!checked) {
        return current.filter((item) => item !== name);
      }
      if (current.includes(name)) {
        return current;
      }
      return [...current, name];
    });
  }

  return (
    <main className="settings-page">
      <header className="settings-title model-settings-title">
        <div>
          <span className="settings-kicker">设置</span>
          <h1>模型管理</h1>
          <p>管理模型供应商、访问凭据和可在对话中选择的模型。</p>
        </div>
        {section === "model" && (
          <Button
            type="text"
            icon={<ReloadOutlined />}
            onClick={() => void reload()}
            loading={loading}
            disabled={fetchingModels}
          >
            刷新
          </Button>
        )}
      </header>

      <section className="model-settings-layout" aria-label="模型管理">
        <aside className="provider-list">
          <div className="provider-list-heading">
            <span>模型供应商</span>
            <span className="provider-count">{sites.length}</span>
          </div>
          <div className="provider-items">
            {loading ? (
              <div className="provider-loading"><LoadingOutlined spin /> 正在读取配置</div>
            ) : sites.length ? sites.map((site) => (
              <button
                className={`provider-item ${site.name === selectedName ? "provider-item-active" : ""}`}
                key={site.name}
                type="button"
                disabled={fetchingModels}
                onClick={() => selectSite(site)}
              >
                <CloudServerOutlined />
                <span className="provider-item-content">
                  <strong>{site.name}</strong>
                  <small>{site.models.length} 个模型</small>
                </span>
              </button>
            )) : (
              <Empty className="provider-empty" image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有供应商" />
            )}
          </div>
          <Button block icon={<PlusOutlined />} onClick={addProvider} disabled={fetchingModels}>
            添加供应商
          </Button>
        </aside>

        <section className="provider-editor">
          <div className="provider-editor-heading">
            <div>
              <span className="settings-kicker">{isNew ? "新供应商" : "供应商配置"}</span>
              <h2>{isNew ? "添加模型供应商" : "编辑模型供应商"}</h2>
            </div>
            {!isNew && (
              <Popconfirm
                title="删除此供应商？"
                description="其中的所有模型配置都会被移除。"
                okText="删除"
                cancelText="取消"
                okButtonProps={{ danger: true }}
                onConfirm={() => void removeProvider()}
              >
                <Button danger icon={<DeleteOutlined />} loading={saving} disabled={fetchingModels}>删除</Button>
              </Popconfirm>
            )}
          </div>

          <div className="settings-form-grid">
            <label className="settings-field settings-field-wide">
              <span>供应商名称</span>
              <Input
                value={draft.name}
                placeholder="例如：Claude"
                maxLength={120}
                onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
              />
            </label>
            <label className="settings-field settings-field-wide">
              <span>API 地址</span>
              <Input
                value={draft.apiUrl}
                placeholder="https://api.example.com"
                maxLength={2048}
                disabled={fetchingModels}
                onChange={(event) => setDraft((current) => ({ ...current, apiUrl: event.target.value }))}
              />
            </label>
            <label className="settings-field">
              <span>API 协议</span>
              <Select
                value={draft.apiProtocol}
                options={[
                  { label: "Anthropic Messages (/v1/messages)", value: "anthropic" },
                  { label: "Chat Completions (/chat/completions)", value: "chat" },
                  { label: "Responses (/responses)", value: "responses" },
                ]}
                onChange={(apiProtocol: ApiProtocol) => setDraft((current) => ({
                  ...current,
                  apiProtocol,
                }))}
              />
            </label>
            <label className="settings-field settings-field-wide">
              <span>API Key</span>
              <Input.Password
                value={draft.apiKey}
                placeholder="输入 API Key"
                maxLength={4096}
                disabled={fetchingModels}
                onChange={(event) => setDraft((current) => ({
                  ...current,
                  apiKey: event.target.value,
                }))}
              />
            </label>
          </div>

          <div className="model-list-heading">
            <div>
              <h3>可用模型</h3>
            </div>
            <div className="model-list-actions">
              <Button
                icon={<CloudDownloadOutlined />}
                loading={fetchingModels}
                disabled={saving}
                onClick={() => void fetchModels()}
              >
                获取模型列表
              </Button>
              <Button
                icon={<PlusOutlined />}
                disabled={fetchingModels}
                onClick={() => setDraft((current) => ({
                  ...current,
                  models: [...current.models, newModel()],
                }))}
              >
                添加模型
              </Button>
            </div>
          </div>

          <div className="model-editor-list">
            {draft.models.length ? draft.models.map((model, index) => (
              <div className="model-editor-row" key={model.draftId}>
                <Input
                  aria-label={`模型 ${index + 1} 名称`}
                  value={model.name}
                  placeholder="模型名称，例如 gpt-4.1"
                  maxLength={120}
                  onChange={(event) => updateModel(index, { name: event.target.value })}
                />
                <Tooltip title="该模型可以接收图片输入">
                  <span className="model-vision-toggle">
                    <PictureOutlined /> 图片理解
                    <Switch
                      size="small"
                      checked={model.image_vision}
                      onChange={(imageVision) => updateModel(index, { image_vision: imageVision })}
                    />
                  </span>
                </Tooltip>
                <Button
                  type="text"
                  danger
                  aria-label={`移除模型 ${index + 1}`}
                  icon={<DeleteOutlined />}
                  onClick={() => removeModel(index)}
                />
                <div className="model-context-setting">
                  <span>上下文</span>
                  <Radio.Group
                    value={
                      model.max_context_tokens === null
                        ? "conservative"
                        : String(model.max_context_tokens)
                    }
                    onChange={(event) => updateModel(index, {
                      max_context_tokens: event.target.value === "conservative"
                        ? null
                        : Number(event.target.value),
                    })}
                  >
                    <Radio value="conservative">保守模式</Radio>
                    <Radio value="0">自动检测上下文</Radio>
                    <Radio value="200000">200K</Radio>
                    <Radio value="256000">256K</Radio>
                    <Radio value="1000000">1M</Radio>
                  </Radio.Group>
                </div>
              </div>
            )) : (
              <div className="model-editor-empty">尚未添加模型。供应商可以先保存，之后再补充模型。</div>
            )}
          </div>

          <div className="settings-save-bar">
            <div aria-live="polite">
              {error && <span className="settings-error">{error}</span>}
              {feedback && <span className="settings-success"><CheckCircleFilled /> {feedback}</span>}
            </div>
            <Button type="primary" onClick={() => void save()} loading={saving}>
              保存配置
            </Button>
          </div>
        </section>
      </section>

      <Modal
        className="model-picker-modal"
        title="选择要添加的模型"
        open={modelPickerOpen}
        width={620}
        okText={`添加选中的模型 (${selectedRemoteNames.length})`}
        cancelText="取消"
        okButtonProps={{ disabled: selectedRemoteNames.length === 0 }}
        onOk={addSelectedModels}
        onCancel={() => setModelPickerOpen(false)}
      >
        <Input
          allowClear
          prefix={<SearchOutlined />}
          value={modelSearch}
          placeholder="搜索模型名称"
          onChange={(event) => setModelSearch(event.target.value)}
        />
        <div className="model-picker-summary">
          <Checkbox
            checked={allFilteredSelected}
            indeterminate={!allFilteredSelected && someFilteredSelected}
            disabled={!selectableFilteredNames.length}
            onChange={(event) => selectFilteredModels(event.target.checked)}
          >
            全选当前结果
          </Checkbox>
          <span>已选 {selectedRemoteNames.length} 个</span>
        </div>
        <div className="remote-model-list">
          {filteredRemoteNames.length ? filteredRemoteNames.map((name) => {
            const alreadyAdded = existingModelNames.has(name);
            const checked = selectedRemoteNames.includes(name);
            return (
              <Checkbox
                className="remote-model-option"
                key={name}
                value={name}
                checked={checked}
                disabled={alreadyAdded}
                onChange={(event) => selectRemoteModel(name, event.target.checked)}
              >
                <span className="remote-model-name">{name}</span>
                {alreadyAdded && <span className="remote-model-added">已添加</span>}
              </Checkbox>
            );
          }) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的模型" />
          )}
        </div>
      </Modal>
    </main>
  );
}
