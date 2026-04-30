# Wiki Schema: Structure & Rules

## 1. 目录规范 (Directory Structure)
- `/entities/`: 具体的“原子”页面。命名格式：`[[名称]]`。包括公司名（如 `[[英伟达]]`）、股票代码（如 `[[600519]]`）、人物等。
- `/concepts/`: 行业术语、技术逻辑。命名格式：`[[术语]]`。如 `[[液冷技术]]`、`[[大模型量化]]`。
- `/sources/`: 原始输入摘要。命名格式：`[[YYYY-MM-DD_来源_主题]]`。如 `[[2026-04-28_x_digest_AI算力日报]]`。

## 2. 页面格式规范 (Page Format)
所有生成的 `.md` 文件必须包含以下标准的 YAML Frontmatter:

```yaml
---
type: {entity|concept|source}
tags: []
aliases: []
created_at: YYYY-MM-DD HH:mm:ss
updated_at: YYYY-MM-DD HH:mm:ss
source_traceability: [] # 记录关联的 raw 文件哈希
---
```

## 3. 链接约定 (Linking Rules)
- **强制双链**：在正文中首次提到已存在的实体或概念时，必须使用 `[[Wikilink]]`。
- **自动关联**：Generate Phase 必须在页面底部生成 `## Related Connections` 章节，自动列出由图谱算法建议的关联点。

## 4. 命名准则 (Naming Conventions)
- 优先使用中文全称作为文件名。
- A 股代码使用纯 6 位数字，如 `[[600519]]`。
- 全球科技公司优先使用其中文常用名，别名存入 aliases。
