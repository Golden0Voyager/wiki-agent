# WikiAgent API 深度优化策略 (A-Lab 2026-04 生产级方案)

## 一、 深度背景：2026-04 A-Lab 模型战力图谱

根据 A-Lab 内部探测数据（`AI_MODELS_SUMMARY.md`），我们不再将 API 视为简单的文本接口，而是根据其**底层算力（LPU/B200）**、**指令微调方向（Coder/Flash/Thinking）**及**地域稳定性**进行分层治理。

### 1.1 核心选型哲学
*   **提取 (Analyze) 走 NVIDIA/Groq**: 知识提取是结构化任务，对“首字延迟 (TTFT)”和“逻辑严密性”要求极高。
*   **生成 (Generate) 走 AIHubMix/Zhipu**: 总结与 Obsidian 格式化是创意任务，对“语感”和“中文编排”要求更高。
*   **兜底走 Tencent/ModelScope**: 保证流水线在极端网络或欠费情况下的生存能力。

---

## 二、 升级版：任务导向型智能路由架构

WikiAgent 的单任务处理流程将拆分为两条平行的决策路径：

### 2.1 路径 A：极速提取链 (The "Extraction" Path)
**目标**：秒级识别实体与概念，确保 JSON 输出 100% 合法。

| 优先级 | Provider | 模型选型 | 核心理由 |
| :--- | :--- | :--- | :--- |
| **L1 (主力)** | **NVIDIA NIM** | `deepseek-v4-flash` | **算力降维打击**：B200 原生推理，首字延迟 < 100ms。 |
| **L2 (极速)** | **Groq** | `qwen/qwen3-32b` | **TPS 之王**：利用 LPU 架构实现瞬间吐字，极速吞噬大文档。 |
| **L3 (稳定)** | **ModelScope** | `DeepSeek-V4-Flash` | **官方镜像**：每日 2000 次请求红利，作为稳定的逻辑支点。 |

### 2.2 路径 B：语义增强链 (The "Generation" Path)
**目标**：生成符合 Obsidian 审美、中文表达地道的知识页面。

| 优先级 | Provider | 模型选型 | 核心理由 |
| :--- | :--- | :--- | :--- |
| **L1 (主力)** | **AIHubMix** | `glm-5.1-air-free` | **Agent 优化**：智谱 5.1 针对任务编排和中文文采有质的提升。 |
| **L2 (智脑)** | **OpenRouter** | `z-ai/glm-4.5-air:free` | **中文标杆**：免费层中语感最接近人类的模型。 |
| **L3 (兜底)** | **Tencent** | `hunyuan-lite` | **永久免费**：250K 窗口，确保超长文档生成的完整性。 |

---

## 三、 深度思考：如何最大化利用你的 12 个 Key？

### 3.1 跨项目算力复用策略
由于 WikiAgent、Quant Lab、Sugar Bee 共享这一套 API 环境，我们需要建立“算力等级保护”：

1.  **精英算力区 (NVIDIA NIM / AIHubMix GPT-5.5)**: 
    *   **WikiAgent**: 仅用于处理复杂的 PDF 论文或深度财报。
    *   **Quant Lab**: 用于实时盘中研判。
2.  **平价算力区 (ModelScope / Groq)**:
    *   **WikiAgent**: 所有的日常摄入（网页剪藏、推文）默认使用此区。
3.  **免费红利区 (Tencent Lite / OpenRouter Free)**:
    *   **X-Digest**: 全部摘要任务指向此区，实现“零成本”高频运行。

### 3.2 智能熔断与恢复机制 (Circuit Breaker)
在 `wiki_service.py` 中实施以下三态逻辑：
*   **CLOSED (正常)**: 请求 L1 Provider。
*   **OPEN (熔断)**: 当连续失败 3 次，将该 Provider 标记为“不可用”并进入 5 分钟冷却期。
*   **HALF-OPEN (探测)**: 冷却期后，允许单个请求尝试恢复。

---

## 四、 核心升级行动 (Action Items)

> [!IMPORTANT]
> **WikiAgent 立即执行动作：**
> 1.  **Provider 链重构**: 将 `_build_provider_chain` 修改为支持双路径（Analyze/Generate 分离）。
> 2.  **适配新模型 ID**: 废弃 `hy3-preview`，升级为 `deepseek-v4-flash` 和 `glm-5.1-air`。
> 3.  **NVIDIA NIM 接口归一化**: 在 `wiki_service` 中添加对 `NVIDIA_API_KEY` 的首选检测逻辑。
> 4.  **ChromaDB 语义检索升级**: `ask_gemini.py` 优先使用 `gemini-3.1-pro` 以获得 2M 上下文支持，彻底解决 RAG 回答时的背景缺失问题。

### 4.1 技术理由 (Deep Why)
- **为什么选 V4 Flash？** 在 A-Lab 测试中，V4 的多语言推理能力在处理混合了英文术语的中文技术文档时，错误率比 V3 降低了 22%。
- **为什么选 GLM-5.1？** 它是目前对“结构化 Markdown 块”生成稳定性最好的模型，极少出现代码块不闭合或 Obsidian 链接断裂的情况。
