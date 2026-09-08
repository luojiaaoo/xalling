---
name: coding-python
description: Python 编码指南和最佳实践。用于编写、审查或重构 Python 代码时。强制执行 PEP 8 风格，通过 py_compile 进行语法验证，执行单元测试，仅使用Python 3.12版本及以上，在可用时使用 uv 进行依赖管理，并采用符合 Python 习惯的模式。开发python项目时必须触发
---

# Python 编码指南

## 代码风格

### PEP 8

- 使用 4 个空格缩进，绝不使用制表符
- 顶层定义前空两行，类内部定义之间空一行
- 导入顺序：标准库 → 第三方库 → 本地模块，并在各组内按字母顺序排列
- 函数/变量使用 snake_case，类使用 PascalCase，常量使用 UPPER_CASE

### 我的

- 如果需要直接通过 import 来执行代码而未在后续代码中使用，请在行尾添加   *# noqa: F401*
- 如果项目目录没有 ruff.toml 文件，则将 asserts/ruff.toml 复制到项目目录
- 对于新建项目，采用协程语法开发
- 尽量避免使用 getattr、setattr
- 用第一性原则进行编码，不要提前把函数抽象，有必要时再抽象

## 提交前检查

```bash
# 语法检查（始终执行）
uv run -m py_compile  *.py

# 如果存在测试，则运行测试
uv run pytest tests/ -v 2>/dev/null || python -m unittest discover -v 2>/dev/null || echo "未找到测试"

# 格式检查（始终执行，执行代码检查和格式化，删除未使用的import）
uv run ruff check . --fix 2>/dev/null
```

## Python 版本

- **最低版本：** Python 3.12
- 绝不使用 Python 2 语法或模式
- 使用现代特性：match 语句、海象运算符、类型提示

## 模块使用偏好

**技术栈**

| 用途               | 工具 / 库                         |
|--------------------|----------------------------------|
| 后端接口框架       | FastAPI                           |
| 服务运行方式       | uvicorn[standard]                 |
| 同步 HTTP 请求     | requests                          |
| 异步 HTTP 请求     | httpx                             |
| 异步 SSE 请求      | httpx-sse                         |
| URL 解析与构建     | [yarl](references/yarl.md)       |
| 同步文件操作       | pathlib                           |
| 异步文件操作       | aiofiles                          |
| 日志记录           | loguru                            |
| 异步 Redis 客户端  | redis-py  |
| 测试框架           | pytest                            |
| 数据库 ORM         | [sqlmodel](references/sqlmodel.md) |
| 配置管理           | pydantic-settings, python-dotenv  |
| 异步框架 | asyncio, asyncer |

**编码规范**

1. http后端接口必须使用 FastAPI 开发。
2. 网络请求必须设置合理的 `timeout`，并捕获网络相关异常（同步用 `requests`，异步用 `httpx`/`httpx-sse`）。
3. 异步场景下必须使用 `async/await`，避免阻塞事件循环。
4. URL 拼接和解析统一使用 `yarl`，禁止字符串拼接。
5. 文件路径处理统一使用 `pathlib`。
6. 异步文件读写必须使用 `aiofiles`。
7. 日志统一使用 `loguru`，**禁止使用 `print()`** 输出调试信息。
8. 数据库 ORM 使用 `sqlmodel`，定义模型继承 `SQLModel`。
9. 配置管理使用 `pydantic-settings` + `python-dotenv`，**从系统环境变量和 `.env` 文件加载**，敏感信息不得硬编码。

## 协程语法使用偏好

> 使用 asyncer 时，请查看[用法文档](references/asyncer.md)

```python
# 程序入口（不使用asyncio原生接口，使用asyncer）
# 多task并发（不使用asyncio原生接口，使用asyncer）
# 包装同步函数为异步（不使用asyncio原生接口，使用asyncer）
# 包装异步函数为同步（使用asyncer，禁止使用！）

# 超时控制
try:
    await asyncio.wait_for(asyncio.sleep(5), timeout=2)
except TimeoutError:
    print("timeout")

# 取消task
async def job():
    while True:
        await asyncio.sleep(1)
async def main():
    task = asyncio.create_task(job())
    await asyncio.sleep(2)
    task.cancel()
    try:
        await task # 此时wait就会抛出异常
    except asyncio.CancelledError:
        pass
```

## 依赖管理

强制要求项目使用uv

```bash
# 项目初始化
uv init --python=3.12
uv venv

# 安装/卸载项目代码依赖包
uv add/remove <package>

# 安装/卸载开发命令行工具（比如 ruff）
uv add/remove --dev <package>

# 运行 python 文件
uv run <file.py>
```

## Pythonic 模式偏好

```python
# ✅ 使用列表/字典推导式，而不是普通循环
squares = [x**2 for x in range(10)]
lookup = {item.id: item for item in items}

# ✅ 使用上下文管理器管理资源
with open("file.txt") as f:
    data = f.read()

# ✅ 使用自定义上下文管理器封装成对的资源操作
from contextlib import contextmanager
from time import perf_counter
@contextmanager
def timer(name: str):
    print('开始')
    try:
        yield ‘ok’
    finally:
        print('结束')
with timer("数据处理") as status:
    print(status)

# ✅ 使用解包
first, *rest = items
a, b = b, a  # 交换

# ✅ EAFP 优于 LBYL
try:
    value = d[key]
except KeyError:
    value = default

# ✅ 使用 f-string 进行格式化
msg = f"你好 {name}，你有 {count} 个项目"

# ✅ 使用类型提示
def process(items: list[str]) -> dict[str, int]:
    ...

# ✅ 使用 dataclasses 表示简单的数据容器
from dataclasses import dataclass

@dataclass
class User:
    name: str
    email: str
    active: bool = True

# ✅ 使用 pydantic 表示严谨的数据容器
# 对系统外来数据强制做校验
from pydantic import BaseModel
class User(BaseModel):
    name: str
    email: str
    active: bool = True

# ✅ 使用 pathlib，而不是 os.path
from pathlib import Path
config = Path.home() / ".config" / "app.json"

# ✅ 使用 enumerate、zip、itertools
for i, item in enumerate(items):
    ...
for a, b in zip(list1, list2, strict=True):
    ...
    
# ✅ 使用带参数的装饰器对函数进行包装（使用类实现，逻辑更加清晰）
import functools
class Repeat:
    def __init__(self, times):
        self.times = times
    def __call__(self, func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            results = []
            for _ in range(self.times):
                results.append(func(*args, **kwargs))
            return results
        return wrapper
@Repeat(3)
def greet(name):
    return f"Hi, {name}!"
```

## 应避免的反模式

```python
# ❌ 可变默认参数
def bad(items=[]):  # Bug：会在多次调用之间共享
    ...
def good(items=None):
    items = items or []

# ❌ 裸 except
try:
    ...
except:  # 会捕获 SystemExit、KeyboardInterrupt
    ...
except Exception:  # 更好
    ...

# ❌ 全局状态
# ❌ from module import *
# ❌ 循环中进行字符串拼接（使用 join）
# ❌ == None（使用 `is None`）
# ❌ len(x) == 0（使用 `not x`）
```

## 测试

- 使用 pytest
- 测试文件命名为 `test_*.py`，测试函数命名为 `test_*`
- 目标是编写聚焦的单元测试，并模拟外部依赖
- 每次提交前运行：`uv run -m pytest -v`

## 文档字符串

```python
def fetch_user(user_id: int, include_deleted: bool = False) -> User | None:
    """通过 ID 从数据库中获取用户。
  
    Args:
        user_id: 唯一的用户标识符。
        include_deleted: 如果为 True，则包含软删除用户。
  
    Returns:
        如果找到则返回 User 对象，否则返回 None。
  
    Raises:
        DatabaseError: 如果连接失败。
    """
```

## 快速检查清单

- [ ] 语法有效（`py_compile`）
- [ ] 测试通过（`pytest`）
- [ ] 公共函数具有类型提示
- [ ] 没有硬编码密钥
- [ ] 使用 f-string，而不是 `.format()` 或 `%`
- [ ] 使用 `pathlib` 处理文件路径
- [ ] 使用上下文管理器进行 I/O
- [ ] 没有可变默认参数