"""后端通用的辅助函数。"""

import os


def normalize_project_path(path: str) -> str:
    """统一 Windows 盘符为大写，避免同一项目因大小写差异被拆成多个分组。

    仅 Windows 文件系统不区分大小写才做归一化；Linux 路径原样返回。
    """
    if (
        os.name == "nt"
        and len(path) >= 2
        and path[1] == ":"
        and path[0].isalpha()
    ):
        return path[0].upper() + path[1:]
    return path
