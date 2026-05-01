# WikiAgent 鲁棒性与准确性增强计划

## 背景

经过对 `wiki_service.py`、`api.py`、`sync_vector_db.py`、`ai_organizer.py` 以及 `schema/` 提示词的全面审计，当前系统已经具备了基本的端到端闭环能力。但在实际运行中暴露出以下几类问题：

1. **鲁棒性缺陷**：队列任务在热重载时全量丢失；`index.md` 累积了大量历史脏数据无法自愈；同一文档重复摄入没有去重机制。
2. **输出准确性问题**：实体/概念命名归一化不彻底（`index.md` 中仍存在 `千问 (Qwen)` 和 `Born Global` 等分裂节点）；大模型 JSON 解析过于脆弱（只处理了 ````json` 一种包裹格式）。
3. **工程缺陷**：`api.py` 有重复 import；`_call_llm_json` 和 `_call_llm_text` 存在大量重复代码；缺少 Provider 级别的 Fallback 机制。

## User Review Required

> [!IMPORTANT]
> 本计划涉及对 `wiki_service.py` 的**核心重构**（提取公共 LLM 调用方法、新增去重层和 Provider Fallback），以及对 `index.md` 的自动清洗。请确认方向后我再动手。

> [!WARNING]  
> `index.md` 清洗会移除所有历史脏链接（如 `千问 (Qwen)`、`Born Global`、`OPC (超级个体)` 等），仅保留实际存在文件的纯中文链接。这是不可逆操作。

## Proposed Changes

### 一、鲁棒性增强

---

#### 1.1 内容去重层 (Deduplication Gate)

#### [MODIFY] [wiki_service.py](file:///Users/hainingyu/Code/knowledge_base/wiki_service.py)

**问题**：当前 `process_ingest_task` 每次调用都会无条件地调用大模型。同一份文档被 `resend.py` 反复发送时，会产生大量重复卡片和冗余向量。

**方案**：在 `process_ingest_task` 入口处增加 **content hash 去重检查**：
- 维护一个本地 `processed_hashes.json` 文件，记录所有已成功处理的 `content_hash`。
- 如果传入内容的 hash 已存在，直接跳过并返回，避免重复消耗 LLM 调用和向量化资源。
- 提供 `force=True` 参数可以强制覆盖重处理。

```python
# 去重检查 (在 process_ingest_task 开头)
processed_path = self.base_dir / "processed_hashes.json"
processed = json.loads(processed_path.read_text()) if processed_path.exists() else []
if content_hash in processed and not payload.get("force"):
    logger.info(f"⏭️ Skipping duplicate: {topic} (hash: {content_hash})")
    return
# ... 处理完成后追加 hash
processed.append(content_hash)
processed_path.write_text(json.dumps(processed))
```

---

#### 1.2 Provider 级别 Fallback（跨供应商降级）

#### [MODIFY] [wiki_service.py](file:///Users/hainingyu/Code/knowledge_base/wiki_service.py)

**问题**：当前系统只会在同一个 Provider 内轮换 Key。如果 OpenRouter 整体宕机或免费额度耗尽，系统会彻底瘫痪。

**方案**：建立 **Provider 优先级链**，当主 Provider 连续 3 次失败后，自动切换到备用 Provider：
```
OpenRouter (hy3-preview:free) → ZhipuAI (glm-4.7-flash) → Hunyuan
```

实现方式：将 `__init__` 中的 Provider 初始化改为构建一个 `providers` 列表，`_call_llm_core` 方法遍历该列表，直到某个 Provider 成功返回。

---

#### 1.3 `index.md` 自动归一化清洗

#### [MODIFY] [wiki_service.py](file:///Users/hainingyu/Code/knowledge_base/wiki_service.py)

**问题**：`index.md` 中积累了大量历史脏链接（`千问 (Qwen)`、`OPC (超级个体)`、`Born Global` 等），这些"幽灵节点"在 Obsidian 图谱中制造噪音。

**方案**：新增 `_sanitize_index()` 方法，在每次 `_update_index` 之后自动执行：
- 扫描 `wiki/entities/` 和 `wiki/concepts/` 目录下实际存在的 `.md` 文件。
- 对比 `index.md` 中的双链列表，移除所有**没有对应实际文件**的悬空链接。
- 这样即使大模型偶尔输出了一个不规范的名称写入了 index，下一轮处理时也会被自动清除。

---

### 二、输出准确性增强

---

#### 2.1 JSON 解析鲁棒化

#### [MODIFY] [wiki_service.py](file:///Users/hainingyu/Code/knowledge_base/wiki_service.py)

**问题**：`_call_llm_json` 中的 JSON 清洗只处理了 ````json\n...\n```` 这一种格式。实际上大模型还可能输出：
- ` ```JSON ` （大写）
- 前后有多余空行
- JSON 外面包了一段解释性文字

**方案**：用更健壮的正则提取 JSON：
```python
# 尝试多种策略提取 JSON
def _extract_json(self, raw_text: str) -> dict:
    # 策略1: 直接解析
    try: return json.loads(raw_text)
    except: pass
    # 策略2: 提取 ```json ... ``` 代码块
    match = re.search(r'```[jJ][sS][oO][nN]?\s*\n(.*?)\n\s*```', raw_text, re.DOTALL)
    if match:
        try: return json.loads(match.group(1))
        except: pass
    # 策略3: 提取第一个 { ... } 块
    match = re.search(r'\{.*\}', raw_text, re.DOTALL)
    if match:
        try: return json.loads(match.group(0))
        except: pass
    raise ValueError(f"Cannot parse JSON from: {raw_text[:200]}")
```

---

#### 2.2 LLM 调用方法 DRY 重构

#### [MODIFY] [wiki_service.py](file:///Users/hainingyu/Code/knowledge_base/wiki_service.py)

**问题**：`_call_llm_json` 和 `_call_llm_text` 有 90% 的代码完全重复（HTTP 请求、429 处理、重试逻辑），违反 DRY 原则，维护困难。

**方案**：提取公共方法 `_call_llm_core`，两个方法变成薄包装：
```python
async def _call_llm_core(self, system_prompt, user_content, max_retries=3) -> str:
    """核心 LLM 调用，返回原始文本"""
    # ... 统一的 HTTP + 429 + 重试 + Provider Fallback 逻辑

async def _call_llm_json(self, ...) -> Dict:
    raw = await self._call_llm_core(...)
    return self._extract_json(raw)

async def _call_llm_text(self, ...) -> str:
    return await self._call_llm_core(...)
```

---

#### 2.3 Frontmatter `tags` 和 `aliases` 充实

#### [MODIFY] [generate_prompt.md](file:///Users/hainingyu/Code/knowledge_base/schema/generate_prompt.md)

**问题**：当前生成的卡片中 `tags` 和 `aliases` 字段经常为空列表 `[]`，浪费了 Obsidian 的标签检索和别名匹配能力。

**方案**：在提示词中明确要求：
- `tags`：必须至少包含 2 个标签（来源分类 + 领域分类）。
- `aliases`：必须包含该实体/概念的**英文名**和常见简称（如"千问"的 aliases 应包含 `["Qwen", "通义千问"]`）。

---

#### 2.4 `generate_prompt.md` 输出格式强化

#### [MODIFY] [generate_prompt.md](file:///Users/hainingyu/Code/knowledge_base/schema/generate_prompt.md)

**问题**：当前提示词只给了来源页（Source Page）的模板，缺少实体页和概念页的模板。大模型在生成这两类页面时格式不统一。

**方案**：补全三种页面的完整模板，并在输出要求中明确：
- **严禁使用 Markdown 代码块包裹输出**（根因修复，从提示词层面杜绝 ````markdown` 泄露）。
- 每个页面必须以 `--- FILE: 路径 ---` 分隔，路径必须是纯中文。

---

### 三、工程质量修复

---

#### 3.1 `api.py` 清理

#### [MODIFY] [api.py](file:///Users/hainingyu/Code/knowledge_base/api.py)

- 修复重复的 `import logging`（第 2 行和第 10 行）。
- 补充 `uvicorn` 和 `httpx` 的日志静音配置。

---

#### 3.2 `resend.py` 集成去重感知

#### [MODIFY] [resend.py](file:///Users/hainingyu/Code/knowledge_base/resend.py)

- 读取 `processed_hashes.json`，在发送前先过滤掉已处理的 hash，避免无意义的网络请求。

---

## Verification Plan

### Automated Tests
1. 停止当前 Uvicorn，重新启动后执行 `uv run python resend.py`。
2. 验证重复文档被跳过（日志中出现 `⏭️ Skipping duplicate`）。
3. 验证新文档（DeepSeek-V4 论文）被正常处理，且输出卡片无反引号泄露。
4. 检查 `wiki/index.md` 中不再存在分裂节点。

### Manual Verification
- 打开 Obsidian 查看关系图谱，确认所有节点为纯中文、无孤岛、无重复。
