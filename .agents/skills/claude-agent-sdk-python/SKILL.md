---
name: claude-agent-sdk-python
description: Build, review, migrate, and troubleshoot Python applications that use Anthropic's `claude-agent-sdk`. Use for `query()`, `ClaudeSDKClient`, sessions, streaming, permissions, hooks, SDK MCP tools, messages/events, tool I/O types, plugins, structured output, errors, and sandbox configuration. Do not use for the low-level Anthropic Messages API unless the Agent SDK is also involved.
---

# Claude Agent SDK Python

Use this skill to produce version-aware, type-accurate Python integrations with the Claude Agent SDK.

## Source of truth

The complete Chinese Python API reference is preserved in [references/official-api-reference.zh-CN.md](references/official-api-reference.zh-CN.md). It is a snapshot of the official page at <https://code.claude.com/docs/zh-CN/agent-sdk/python>, retrieved on 2026-09-09.

The snapshot is intentionally exhaustive. Do not load all of it for an ordinary task. Read [references/topic-index.md](references/topic-index.md), then search the official snapshot for the exact API names and read only the matching section. For example:

```powershell
rg -n '<h[234] id="(claudeagentoptions|canusetool|permissionresultallow)">' references/official-api-reference.zh-CN.md
```

When the user needs current-version behavior, when their installed package differs from the snapshot, or when an API may have changed, inspect the installed `claude-agent-sdk` version and verify against the current official page. State any version mismatch explicitly.

## Workflow

1. Classify the request using the routing table below.
2. Inspect the project's Python version, installed SDK version, dependency files, and existing async architecture when code is involved.
3. Read the exact reference sections for every API used. Confirm signatures, defaults, unions, literal values, return/message variants, and documented exceptions instead of relying on memory.
4. Choose `query()` for isolated exchanges and `ClaudeSDKClient` for a connection with continued context, follow-up turns, interruption, or explicit lifecycle control.
5. Keep message consumption asynchronous. Narrow on concrete message and content-block types before accessing variant-specific fields.
6. Treat permissions, hooks, and sandbox escape paths as security boundaries. Preserve the user's authorization scope and use the least-permissive configuration that satisfies the request.
7. Implement the smallest complete change, then run syntax checks and relevant tests. For runnable examples, include imports, `asyncio.run(...)`, and cleanup/context management where required.

## Topic routing

| Need | Read these sections in the official snapshot |
| --- | --- |
| Install or decide the interaction model | `installation`; `choosing-between-query-and-claudesdkclient` |
| One-shot or streaming requests | `query`; `ClaudeAgentOptions`; `Message` and concrete message/content-block types |
| Persistent conversations or interruption | `ClaudeSDKClient`; its methods and examples; advanced client features |
| Define Python-hosted MCP tools | `tool`; `ToolAnnotations`; `create_sdk_mcp_server`; `SdkMcpTool`; MCP server config types |
| List, inspect, rename, tag, or resume sessions | `list_sessions`; `get_session_messages`; `get_session_info`; `rename_session`; `tag_session`; `resume`; `continue_conversation` |
| Configure models, prompts, tools, settings, agents, output, plugins, or beta flags | `ClaudeAgentOptions`; `OutputFormat`; `SystemPromptPreset`; `SystemPromptFile`; `SettingSource`; `AgentDefinition`; `ToolsPreset`; `ThinkingConfig`; `EffortLevel`; `SdkBeta`; `SdkPluginConfig` |
| Implement runtime permission decisions | `CanUseTool`; `ToolPermissionContext`; `PermissionResult*`; `PermissionUpdate`; `PermissionRuleValue`; `PermissionMode` |
| Consume responses and progress | `message-types`; `content-block-types`; `StreamEvent`; rate-limit and task message types |
| Handle failures | `error-types`; `AssistantMessageError`; example `error-handling` |
| Add lifecycle hooks | all of `hook-types`, especially the exact event input and output union for the chosen event |
| Type built-in tool calls/results | `tool-input/output-types` and the subsection for that exact tool |
| Configure process/filesystem/network isolation | `sandbox-configuration`; `SandboxSettings`; `SandboxNetworkConfig`; `SandboxIgnoreViolations`; permissions fallback |

## Critical invariants

- `query()` starts a new session by default. Continue only with the documented `continue_conversation` or `resume` options. `ClaudeSDKClient` automatically reuses its connected conversation.
- Both entry points support streaming input, hooks, and custom tools; interruption is a client capability, not a `query()` capability.
- `query()` returns `AsyncIterator[Message]`. Do not assume every emitted item is an assistant text response; system, result, stream, rate-limit, and task-related variants may appear.
- Session discovery and metadata helpers in this reference are synchronous even though request execution is asynchronous. Preserve their pagination, project-directory, worktree, validation, and not-found semantics.
- `@tool` handlers are async and return MCP content dictionaries. Simple Python type maps and full JSON Schema are different supported schema forms.
- `ToolAnnotations` are client hints, not an authorization mechanism. Never use `readOnlyHint`, `destructiveHint`, `idempotentHint`, or `openWorldHint` as a security decision by themselves.
- Match MCP tool permission names using the documented `mcp__<server>__<tool>` form.
- `setting_sources` controls which filesystem settings are loaded; an empty list opts out. Confirm precedence and `CLAUDE.md` implications before changing it.
- Permission callbacks must return the documented allow/deny structures. Preserve updated input and permission-update behavior when used, and give denials actionable messages where appropriate.
- Hook callback input/output shapes vary by event. Do not reuse fields across events without checking the corresponding `TypedDict` and sync/async hook output contract.
- Structured output, partial-message streaming, thinking configuration, and slow/stalled-response controls are opt-in and interact with specific options. Read their exact option documentation together before combining them.
- Sandbox `excludedCommands` statically bypasses sandboxing for listed commands, whereas `allowUnsandboxedCommands` permits the model to request escape at runtime. Such requests fall back to permissions unless permissions are bypassed. The combination of sandbox escape and `bypassPermissions` can silently remove isolation and requires explicit user authorization.
- A custom `Transport` is an advanced extension point. Follow its abstract interface and lifecycle exactly; do not substitute an arbitrary subprocess or HTTP object.

## Implementation guidance

- Prefer explicit imports from `claude_agent_sdk` and type annotations that reflect the documented unions.
- Preserve async cancellation and close/disconnect clients deterministically, preferably with the documented async context manager.
- For streaming user input, yield the documented user-message dictionary shape; do not pass an ordinary synchronous iterator.
- For tool-result rendering, handle both text and non-text MCP content where the task can produce them.
- For error handling, catch the narrow SDK exception subclasses that the operation can raise and retain process exit/stderr or JSON-decode context for diagnostics.
- If a user asks for a complete API inventory, use the snapshot and topic index rather than generating an incomplete list from memory.

## Reference discipline

- Cite the official page link when explaining externally verifiable SDK behavior.
- Keep copied excerpts short in user-facing prose; prefer accurate paraphrase and working code.
- Do not silently generalize examples into requirements. Distinguish documented defaults, optional patterns, and security warnings.
- When code and the snapshot disagree, prefer the installed package's inspectable public types for that version, then explain the discrepancy and recommend a compatible path.
