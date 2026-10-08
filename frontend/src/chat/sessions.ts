import type { ChatSessionSummary } from "../api/client";

export type ChatSessionGroup = {
  key: string;
  createdAt: number;
  name: string;
  path: string;
  sessions: ChatSessionSummary[];
};

/** Sort by creation time; missing dates and ties use stable identifiers. */
export function groupChatSessions(
  sessions: ChatSessionSummary[],
  defaultProjectPath: string | null,
): ChatSessionGroup[] {
  const grouped = new Map<string, ChatSessionSummary[]>();
  for (const session of sessions) {
    const key = session.cwd || "__unknown_project__";
    const group = grouped.get(key) ?? [];
    group.push(session);
    grouped.set(key, group);
  }
  const groups = [...grouped.entries()]
    .map(([key, groupSessions]) => {
      const sortedSessions = [...groupSessions].sort((left, right) => (
        (right.created_at ?? 0) - (left.created_at ?? 0)
        || left.session_id.localeCompare(right.session_id)
      ));
      const latest = sortedSessions[0];
      return {
        key,
        createdAt: latest.created_at ?? 0,
        name: latest.cwd?.split(/[\\/]/).filter(Boolean).at(-1) ?? "未知工作区",
        path: latest.cwd ?? "",
        sessions: sortedSessions,
      };
    })
    .sort((left, right) => (
      right.createdAt - left.createdAt || left.key.localeCompare(right.key)
    ));
  if (defaultProjectPath) {
    const pinnedIndex = groups.findIndex((group) => group.key === defaultProjectPath);
    if (pinnedIndex > 0) {
      groups.unshift(...groups.splice(pinnedIndex, 1));
    }
  }
  return groups;
}
