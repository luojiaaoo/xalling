import { ArrowUpOutlined, FolderOutlined, HomeOutlined, RightOutlined } from "@ant-design/icons";
import { Alert, Button, Input, Modal, Select, Space, Spin } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";

import { listDirectories, listRootDirectories, type DirectoryListing, type ProjectFolder } from "../api/client";

type ProjectFolderDialogProps = {
  initialPath: string | null;
  onCancel: () => void;
  onSelect: (project: ProjectFolder) => void;
};

export function ProjectFolderDialog({ initialPath, onCancel, onSelect }: ProjectFolderDialogProps) {
  const [listing, setListing] = useState<DirectoryListing | null>(null);
  const [selectedFolder, setSelectedFolder] = useState<ProjectFolder | null>(null);
  const [pathInput, setPathInput] = useState(initialPath ?? "");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [roots, setRoots] = useState<ProjectFolder[]>([]);
  const [rootsLoading, setRootsLoading] = useState(true);
  const [rootsError, setRootsError] = useState("");
  const requestId = useRef(0);

  const browse = useCallback(async (path: string | null) => {
    const id = ++requestId.current;
    setLoading(true);
    setSelectedFolder(null);
    setError("");
    try {
      const result = await listDirectories(path);
      if (id !== requestId.current) return;
      setListing(result);
      setPathInput(result.current.path);
    } catch (failure) {
      if (id === requestId.current) {
        setError(failure instanceof Error ? failure.message : "读取文件夹失败，请重试。");
      }
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void browse(initialPath);
    return () => { ++requestId.current; };
  }, [browse, initialPath]);

  useEffect(() => {
    let active = true;
    void listRootDirectories()
      .then((folders) => { if (active) setRoots(folders); })
      .catch(() => { if (active) setRootsError("一级目录读取失败，可直接输入完整路径。"); })
      .finally(() => { if (active) setRootsLoading(false); });
    return () => { active = false; };
  }, []);

  const canSelect = Boolean(listing && !loading && !error && pathInput === listing.current.path);
  const currentPath = listing?.current.path ?? "";
  const selectedRoot = [...roots].sort((a, b) => b.path.length - a.path.length).find(({ path }) => (
    currentPath === path || currentPath.startsWith(path.endsWith("/") || path.endsWith("\\") ? path : `${path}/`)
  ))?.path;
  const pathPrefix = selectedRoot
    ? selectedRoot.endsWith("/") || selectedRoot.endsWith("\\") ? selectedRoot : `${selectedRoot}/`
    : "";
  const relativePath = pathInput === selectedRoot ? ""
    : pathPrefix && pathInput.startsWith(pathPrefix) ? pathInput.slice(pathPrefix.length) : pathInput;

  return (
    <Modal
      open
      centered
      title="选择项目文件夹"
      width={640}
      onCancel={onCancel}
      onOk={() => { if (canSelect && listing) onSelect(selectedFolder ?? listing.current); }}
      okText={selectedFolder ? "选择文件夹" : "选择当前文件夹"}
      cancelText="取消"
      okButtonProps={{ disabled: !canSelect }}
    >
      <div className="project-folder-picker">
        <Space.Compact block className="project-folder-pathbar">
          <Select
            className="project-folder-root-select"
            aria-label="一级目录"
            placeholder="一级目录"
            value={selectedRoot}
            options={roots.map((folder) => ({ label: folder.path, value: folder.path }))}
            loading={rootsLoading}
            disabled={loading || rootsLoading || !roots.length}
            popupMatchSelectWidth={220}
            onChange={(path: string) => void browse(path)}
          />
          <Input.Search
            aria-label="项目文件夹路径"
            placeholder={selectedRoot ? "子目录路径" : "输入完整文件夹路径"}
            value={relativePath}
            onChange={(event) => {
              const value = event.target.value;
              setSelectedFolder(null);
              setPathInput(selectedRoot ? value ? `${pathPrefix}${value}` : selectedRoot : value);
            }}
            onSearch={() => { if (pathInput.trim() && !loading) void browse(pathInput.trim()); }}
            enterButton="前往"
            loading={loading}
            disabled={loading}
          />
        </Space.Compact>
        <div className="project-folder-navigation">
          <Button
            disabled={loading || !listing?.parent_path}
            icon={<ArrowUpOutlined />}
            onClick={() => { if (listing?.parent_path) void browse(listing.parent_path); }}
          >
            返回上级
          </Button>
          <Button disabled={loading} icon={<HomeOutlined />} onClick={() => void browse(null)}>
            默认目录
          </Button>
        </div>
        {(error || rootsError) && <Alert type="error" showIcon title={error || rootsError} />}
        <Spin spinning={loading}>
          <div className="project-folder-list" role="list" aria-label="子文件夹">
            {listing?.directories.map((folder) => (
              <div role="listitem" key={folder.path}>
                <Button
                  block
                  color={selectedFolder?.path === folder.path ? "primary" : "default"}
                  variant={selectedFolder?.path === folder.path ? "filled" : "text"}
                  className="project-folder-entry"
                  aria-pressed={selectedFolder?.path === folder.path}
                  disabled={loading}
                  icon={<FolderOutlined />}
                  title={folder.path}
                  onClick={() => setSelectedFolder(folder)}
                  onDoubleClick={() => { if (!loading) void browse(folder.path); }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !loading) {
                      event.preventDefault();
                      void browse(folder.path);
                    }
                  }}
                >
                  <span className="project-folder-name">{folder.name}</span>
                  <RightOutlined />
                </Button>
              </div>
            ))}
            {!loading && !listing?.directories.length && (
              <div className="project-folder-empty">{error ? "无法读取目录" : "此目录下没有子文件夹"}</div>
            )}
          </div>
        </Spin>
      </div>
    </Modal>
  );
}
