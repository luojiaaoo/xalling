import {
  CheckCircleFilled,
  CloudServerOutlined,
  DeleteOutlined,
  LoadingOutlined,
  PictureOutlined,
  PlusOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { Button, Empty, Input, Popconfirm, Switch, Tooltip } from "antd";
import { useEffect, useState } from "react";

import {
  deleteModelSite,
  getModelSites,
  saveModelSite,
  type ModelConfig,
  type ModelSite,
} from "../bridge/client";

type ProviderDraft = {
  originalName: string | null;
  name: string;
  apiUrl: string;
  apiKey: string;
  models: ModelConfig[];
};

function newDraft(): ProviderDraft {
  return {
    originalName: null,
    name: "",
    apiUrl: "",
    apiKey: "",
    models: [],
  };
}

function draftFromSite(site: ModelSite): ProviderDraft {
  return {
    originalName: site.name,
    name: site.name,
    apiUrl: site.api_url,
    apiKey: site.api_key,
    models: site.models.map((model) => ({ ...model })),
  };
}

function formatBridgeError(error: unknown): string {
  return error instanceof Error ? error.message : "保存失败，请稍后重试。";
}

export function ModelSettings({ section }: { section: string }) {
  const [sites, setSites] = useState<ModelSite[]>([]);
  const [draft, setDraft] = useState<ProviderDraft>(newDraft);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
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
        })),
      );
      await reload(nextName);
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
      setFeedback("供应商已删除。");
    } catch (deleteError) {
      setError(formatBridgeError(deleteError));
    } finally {
      setSaving(false);
    }
  }

  const isNew = draft.originalName === null;

  return (
    <main className="settings-page">
      <header className="settings-title model-settings-title">
        <div>
          <span className="settings-kicker">设置</span>
          <h1>模型管理</h1>
          <p>管理模型供应商、访问凭据和可在对话中选择的模型。</p>
        </div>
        {section === "model" && (
          <Button type="text" icon={<ReloadOutlined />} onClick={() => void reload()} loading={loading}>
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
          <Button block icon={<PlusOutlined />} onClick={addProvider}>
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
                <Button danger icon={<DeleteOutlined />} loading={saving}>删除</Button>
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
                placeholder="https://api.example.com/v1"
                maxLength={2048}
                onChange={(event) => setDraft((current) => ({ ...current, apiUrl: event.target.value }))}
              />
            </label>
            <label className="settings-field settings-field-wide">
              <span>API Key</span>
              <Input.Password
                value={draft.apiKey}
                placeholder="输入 API Key"
                maxLength={4096}
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
            <Button
              icon={<PlusOutlined />}
              onClick={() => setDraft((current) => ({
                ...current,
                models: [...current.models, { name: "", image_vision: false }],
              }))}
            >
              添加模型
            </Button>
          </div>

          <div className="model-editor-list">
            {draft.models.length ? draft.models.map((model, index) => (
              <div className="model-editor-row" key={`${model.name}-${index}`}>
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
    </main>
  );
}
