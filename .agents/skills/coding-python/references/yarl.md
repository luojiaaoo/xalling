# yarl

## 1. 概述

`yarl.URL` 表示一个 URL，格式为：

- 绝对 URL：
  `[scheme:]//[user[:password]@]host[:port][/path][?query][#fragment]`
- 相对 URL：
  `[/path][?query][#fragment]`

### URL 各部分名称
```
 http://user:pass@example.com:8042/over/there?name=ferret#nose
 \__/   \__/ \__/ \_________/ \__/\_________/ \_________/ \__/
  |      |    |        |       |      |           |        |
scheme  user password host    port   path       query   fragment
```

**编码规则**
- 所有数据在内部都以**百分号编码**（percent-encoding）存储（`user`、`path`、`query`、`fragment`）。
- `host` 部分以 **IDNA 编码**（RFC 5891）存储。
- 构造函数和修改操作符会自动编码，库默认使用 **UTF-8** 来进行百分号编码。

```python
>>> URL('http://example.com/path/to/?arg1=a&arg2=b#fragment')
URL('http://example.com/path/to/?arg1=a&arg2=b#fragment')
```

如果 URL 中只包含 ASCII 字符，编码前后没有区别。对于非 ASCII 字符，会自动编码：

```python
>>> str(URL('http://εμπορικόσήμα.eu/шлях/這裡'))
'http://xn--jxagkqfkduily1i.eu/%D1%88%D0%BB%D1%8F%D1%85/%E9%80%99%E8%A3%A1'
```

已经编码的 URL 不会被重复编码：

```python
>>> URL('http://xn--jxagkqfkduily1i.eu')
URL('http://xn--jxagkqfkduily1i.eu')
```

**人类可读形式** 通过 `human_repr()` 获得：

```python
>>> url = URL('http://εμπορικόσήμα.eu/шлях/這裡')
>>> str(url)
'http://xn--jxagkqfkduily1i.eu/%D1%88%D0%BB%D1%8F%D1%85/%E9%80%99%E8%A3%A1'
>>> url.human_repr()
'http://εμπορικόσήμα.eu/шлях/這裡'
```

> **注意**
> 某些 Web 服务器可能不接受 yarl 的默认编码。
> 构造时传入 `encoded=True` 可以阻止自动编码，此时用户需自行保证 URL 的正确性。
> 不建议在没有必要的情况下使用该选项，因为后续操作仍可能对部分内容重新编码。

---

## 2. 属性

所有属性分为**已解码**和**已编码**（`raw_` 前缀）两类版本。

### 2.1 `scheme`
- `URL.scheme`：绝对 URL 的 scheme，相对 URL 或 `//` 开头的 URL 返回空字符串。

```python
>>> URL('http://example.com').scheme
'http'
>>> URL('//example.com').scheme
''
>>> URL('page.html').scheme
''
```

### 2.2 `user` / `raw_user`
- `URL.user`：已解码的用户名，若不存在则为 `None`。
- `URL.raw_user`：已编码的用户名，若不存在则为 `None`。

```python
>>> URL('http://john@example.com').user
'john'
>>> URL('http://бажан@example.com').user
'бажан'
>>> URL('http://example.com').user is None
True
>>> URL('http://довбуш@example.com').raw_user
'%D0%B4%D0%BE%D0%B2%D0%B1%D1%83%D1%88'
```

### 2.3 `password` / `raw_password`
- `URL.password`：已解码的密码，若不存在则为 `None`。
- `URL.raw_password`：已编码的密码，若不存在则为 `None`。

```python
>>> URL('http://john:pass@example.com').password
'pass'
>>> URL('http://степан:пароль@example.com').password
'пароль'
>>> URL('http://example.com').password is None
True
>>> URL('http://user:пароль@example.com').raw_password
'%D0%BF%D0%B0%D1%80%D0%BE%D0%BB%D1%8C'
```

### 2.4 `host` / `raw_host` / `host_subcomponent` / `host_port_subcomponent`
- `URL.host`：已解码（IDNA）的主机名，IPv6 地址去掉方括号并压缩，相对 URL 为 `None`。
- `URL.raw_host`：IDNA 编码的主机名，相对 URL 为 `None`。
- `URL.host_subcomponent`：[RFC 3986 3.2.2] 主机子成分（已编码，IPv6 带方括号）。v1.13 添加。
- `URL.host_port_subcomponent`：主机和端口子成分（已编码），末尾点号会被去掉，若端口为 scheme 默认端口则省略端口。v1.17 添加。

```python
>>> URL('http://example.com').host
'example.com'
>>> URL('http://хост.домен').host
'хост.домен'
>>> URL('http://хост.домен').raw_host
'xn--n1agdj.xn--d1acufc'
>>> URL('http://[::1]').host
'::1'
>>> URL('http://хост.домен').host_subcomponent
'xn--n1agdj.xn--d1acufc'
>>> URL('http://[::1]').host_subcomponent
'[::1]'
>>> URL('http://хост.домен:81').host_port_subcomponent
'xn--n1agdj.xn--d1acufc:81'
>>> URL('http://example.com./').host_port_subcomponent
'example.com'                # 末尾点号被移除
>>> URL('http://[::1]').host_port_subcomponent
'[::1]'                      # 默认端口80被省略
```

### 2.5 `port` / `explicit_port`
- `URL.port`：端口号；若未显式指定，则根据 scheme 返回默认端口；相对 URL 或没有默认端口时返回 `None`。
- `URL.explicit_port`：只返回显式指定的端口，若无则返回 `None`。v1.3 添加。

```python
>>> URL('http://example.com:8080').port
8080
>>> URL('http://example.com').port
80
>>> URL('http://example.com').explicit_port is None
True
>>> URL('/path').port is None
True
```

### 2.6 `authority` / `raw_authority`
- `URL.authority`：已解码的 authority 部分（`[user[:password]@]host[:port]`），若全部缺失则为空字符串。v1.5 添加。
- `URL.raw_authority`：已编码的 authority 部分。

```python
>>> URL('http://john:pass@example.com:8000').authority
'john:pass@example.com:8000'
>>> URL('http://john:pass@хост.домен:8000').raw_authority
'john:pass@xn--n1agdj.xn--d1acufc:8000'
```

### 2.7 `path` / `path_safe` / `path_qs` / `raw_path` / `raw_path_qs`
- `URL.path`：已解码的 path，绝对 URL 无 path 时返回 `'/'`。
- `URL.path_safe`：类似 `path`，但不解码 `%2F` 和 `%25`，便于区分斜杠与编码斜杠。v1.12 添加。
- `URL.path_qs`：已解码的 path + query。
- `URL.raw_path`：已编码的 path。
- `URL.raw_path_qs`：已编码的 path + query。

```python
>>> URL('http://example.com/шлях/сюди').path
'/шлях/сюди'
>>> URL('http://example.com/шлях/сюди').raw_path
'/%D1%88%D0%BB%D1%8F%D1%85/%D1%81%D1%8E%D0%B4%D0%B8'
>>> URL('http://example.com/шлях/сюди?ключ=знач').path_qs
'/шлях/сюди?ключ=знач'
>>> URL('http://example.com/шлях/сюди?ключ=знач').raw_path_qs
'/%D1%88%D0%BB%D1%8F%D1%85/%D1%81%D1%8E%D0%B4%D0%B8?%D0%BA%D0%BB%D1%8E%D1%87=%D0%B7%D0%BD%D0%B0%D1%87'
```

### 2.8 `query_string` / `raw_query_string`
- `URL.query_string`：已解码的 query 字符串，无 query 时为空字符串。
- `URL.raw_query_string`：已编码的 query 字符串。

```python
>>> URL('http://example.com/path?ключ=знач').query_string
'ключ=знач'
>>> URL('http://example.com/path?ключ=знач').raw_query_string
'%D0%BA%D0%BB%D1%8E%D1%87=%D0%B7%D0%BD%D0%B0%D1%87'
```

### 2.9 `fragment` / `raw_fragment`
- `URL.fragment`：已解码的 fragment，无 fragment 时为空字符串。
- `URL.raw_fragment`：已编码的 fragment。

```python
>>> URL('http://example.com/path#якір').fragment
'якір'
>>> URL('http://example.com/path#якір').raw_fragment
'%D1%8F%D0%BA%D1%96%D1%80'
```

### 2.10 path 各部分
- `URL.parts`：已解码的 path 元组，如 `('/', 'path', 'to')`。
- `URL.raw_parts`：已编码的 path 元组。
- `URL.name`：已解码的最后一个 path 部分。
- `URL.raw_name`：已编码的最后一个 path 部分。
- `URL.suffix`：已解码的文件扩展名，如 `'.txt'`。
- `URL.raw_suffix`：已编码的文件扩展名。
- `URL.suffixes`：已解码的文件扩展名列表，如 `('.tar', '.gz')`。
- `URL.raw_suffixes`：已编码的文件扩展名列表。

```python
>>> URL('http://example.com/шлях/сюди').parts
('/', 'шлях', 'сюди')
>>> URL('http://example.com/шлях/сюди').name
'сюди'
>>> URL('http://example.com/шлях.тут.ось').suffixes
('.тут', '.ось')
```

### 2.11 `query` 参数
- `URL.query`：返回一个 `multidict.MultiDictProxy`，表示已解码的查询参数。无 query 时为空。

```python
>>> URL('http://example.com/path?a1=a&a2=b').query
<MultiDictProxy('a1': 'a', 'a2': 'b')>
>>> URL('http://example.com/path?ключ=знач').query
<MultiDictProxy('ключ': 'знач')>
```

---

## 3. 绝对与相对 URL

- `URL.absolute`：返回 `True` 表示绝对 URL（拥有 scheme 或以 `//` 开头），否则 `False`。

```python
>>> URL('http://example.com').absolute
True
>>> URL('//example.com').absolute
True
>>> URL('/path/to').absolute
False
```

---

## 4. 生成新的 URL

`URL` 是不可变对象，以下方法均返回新的 `URL` 实例。

### 4.1 构造方法 `URL.build()`
```python
>>> URL.build(scheme="http", host="example.com")
URL('http://example.com')
>>> URL.build(scheme="http", host="example.com", query={"a": "b"})
URL('http://example.com/?a=b')
>>> URL.build(scheme="http", host="example.com", query_string="a=b")
URL('http://example.com/?a=b')
>>> URL.build()
URL('')
```
**注意**：`query` 和 `query_string` 不能同时指定。

### 4.2 替换各部分
- `URL.with_scheme(scheme)`
- `URL.with_user(user)` （传入 `None` 会清除用户和密码）
- `URL.with_password(password)` （传入 `None` 清除密码）
- `URL.with_host(host)` （相对 URL 不允许更改 host，应用 `join()`）
- `URL.with_port(port)` （传入 `None` 恢复为默认端口）
- `URL.with_path(path, *, keep_query=False, keep_fragment=False)` v1.18 新增参数
- `URL.with_query(query)` 或 `URL.with_query(**kwargs)`
  支持映射（如 `dict`、`MultiDict`）、字符串、`(key, value)` 列表。值可以是 `str`、`float`、`int`（除 `bool`）或其列表。`None` 清除 query。
- `URL.update_query(query)` 或 `URL.update_query(**kwargs)`
  更新部分 query 参数，相同的 key 会覆盖（多个值会全量替换）。支持 `%` 运算符形式：`url % {'c': 'd'}`。
- `URL.extend_query(query)` 或 `URL.extend_query(**kwargs)`
  扩展 query 参数，保留重复的 key。v1.11.0 添加。
- `URL.without_query_params(*query_params)`
  移除指定的 query 参数。v1.10.0 添加。
- `URL.with_fragment(fragment)` （传入 `None` 清除 fragment）
- `URL.with_name(name, *, keep_query=False, keep_fragment=False)` 替换路径最后一部分。
- `URL.with_suffix(suffix, *, keep_query=False, keep_fragment=False)` 替换文件扩展名。

大多数修改方法都会自动编码非 ASCII 字符。

```python
>>> URL('http://example.com/path?a=b').with_query({'кл': 'зн'})
URL('http://example.com/path?%D0%BA%D0%BB=%D0%B7%D0%BD')
>>> URL('http://example.com/path?a=b&b=1').update_query(b='2')
URL('http://example.com/path?a=b&b=2')
>>> URL('http://example.com/path?a=b&b=1').extend_query(b='2')
URL('http://example.com/path?a=b&b=1&b=2')
```

### 4.3 路径拼接
- `URL / 'subpath'` 或 `URL.joinpath('to', 'subpath', encoded=False)`
  在原有 path 后追加路径片段，并清除 query 和 fragment。
- `URL.join(url)`
  基于当前 URL 解析相对 URL，进行标准的 URL 拼接。

```python
>>> URL('http://example.com/path?arg#frag') / 'to'
URL('http://example.com/path/to')
>>> URL('http://example.com/path/index.html').join(URL('page.html'))
URL('http://example.com/path/page.html')
>>> URL('http://example.com/path/index.html').join(URL('//python.org/page.html'))
URL('http://python.org/page.html')
```

### 4.4 其他便捷属性
- `URL.parent`：返回 path 去除最后一部分的 URL，同时清除 query 和 fragment。
- `URL.origin()`：返回仅包含 scheme、host 和 port 的 URL。
- `URL.relative()`：返回仅包含 path、query 和 fragment 的相对 URL。

```python
>>> URL('http://example.com/path/to?arg#frag').parent
URL('http://example.com/path')
>>> URL('http://user:pass@example.com/path').origin()
URL('http://example.com')
>>> URL('http://example.com/path/to?arg#frag').relative()
URL('/path/to?arg#frag')
```

---

## 5. 人类可读表示

`URL.human_repr()` 返回已解码且易于阅读的字符串。

```python
>>> url = URL('http://εμπορικόσήμα.eu/這裡')
>>> url.human_repr()
'http://εμπορικόσήμα.eu/這裡'
```

---

## 6. 默认端口检测

`yarl` 内置以下 scheme → 端口映射：

| scheme | 默认端口 |
|--------|----------|
| `http` | 80       |
| `https`| 443      |
| `ws`   | 80       |
| `wss`  | 443      |

`URL.is_default_port()` 判断当前端口是否等于 scheme 的默认端口。

```python
>>> URL('http://example.com').is_default_port()
True
>>> URL('http://example.com:8080').is_default_port()
False
>>> URL('/path/to').is_default_port()
False
```

---

## 7. 缓存控制

由于 IDNA 转换和主机编码开销较大，`yarl` 使用全局 LRU 缓存。

- `yarl.cache_clear()`
  清空 IDNA 编码/解码以及主机编码缓存。
- `yarl.cache_info()`
  返回缓存命中统计字典。
- `yarl.cache_configure(*, idna_encode_size=256, idna_decode_size=256, encode_host_size=512)`
  设置各个缓存大小，传入 `None` 表示无上限（会增大内存占用）。

```python
>>> yarl.cache_info()
{'idna_encode': CacheInfo(hits=5, misses=5, maxsize=256, currsize=5),
 'idna_decode': CacheInfo(hits=24, misses=15, maxsize=256, currsize=15),
 'encode_host': CacheInfo(hits=0, misses=0, maxsize=512, currsize=0)}
```

> **注意**：自 v1.16 起，`ip_address` 和 `host_validate` 缓存已合并为 `encode_host` 缓存。