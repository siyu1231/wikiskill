---
name: wikiskill
description: Drive the wikiskill CLI to evolve agent skills.
version: 0.1.0
author: zhu, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [wikiskill, skill-evolution, wiki, cli]
---

# WikiSkill Skill

WikiSkill 把 agent 的失败轨迹编译成可复用的 skill（论文 arXiv:2608.27454 的复现）。
**引擎是 CLI**：三层 workspace（raw/ 不可变、wiki/ 持久、skills/ 生效）+ 演化循环
（rollout → wiki 维护 → skill 提案 → val 门控 → 审计），状态全部是文件。
本 skill 只是遥控器：教 agent 何时、如何驱动这个 CLI。

## When to Use

- 用户要"跑 WikiSkill / 演化 skill / 让 agent 自己沉淀经验"
- 要查看某 workspace 的演化状态、门控历史、wiki 内容
- 用户报"跑不起来 / 端点不通"——先做环境自检
- 用户想把自己的任务集接入演化

**Don't use for:** 一次性问答；直接读 workspace 产物回答（用 `read_file` 查文件即可，
不必启动 CLI）；给已有 workspace 手工改 `raw/` 或 `skill-impact.md`（只读，禁止写）。
另一个 agent 必做的前置：用户要"优化/演化某个 skill"时，**先按下方任务规范建 tasks.jsonl
并过 `tasks check`**，再进 evolve 流程——引擎不会替你出题。

## Prerequisites

- 项目路径（本机）：`E:/code/wikiskill`，CLI 在其 venv 内（迁移后请自行改路径）：
  ```
  WK=E:/code/wikiskill/.venv/Scripts/wikiskill.exe
  ```
- `--backend hermes`：需要 hermes CLI（本机已装）。
- `--runner direct`：需要 `--llm-base / --llm-key / --llm-model` 或
  `OPENAI_BASE_URL / OPENAI_API_KEY`。默认 `runner=backend` 走 agent CLI，**零额外凭证**。

## How to Run

全部通过 `terminal` 工具执行。evolve 是长任务（hermes 后端 iters 3 实测约 8 分钟、
~50 次 agent 调用）：**必须 background 起、再 wait/poll**，不要前台阻塞：

```
terminal(command=f'{WK} evolve <ws> --iters 3', background=true, timeout=1800)
```

mock 后端（零成本、秒级）适合先验证流程。

## Quick Reference

| 命令 | 作用 |
|---|---|
| `wikiskill doctor [ws] [--probe-llm]` | 环境自检（先跑这个） |
| `wikiskill tasks check <file.jsonl>` | 任务集体检（**写任务必过**，0 failed 才往下走） |
| `wikiskill init <ws> [--backend mock\|hermes] [--tasks f.jsonl] [--seed N]` | 建 workspace + 划分 train/val |
| `wikiskill evolve <ws> --iters N [-q]` | 跑 Algorithm 1 演化循环 |
| `wikiskill status <ws>` | 三层状态 + 门控历史 + R_best |
| `wikiskill run-task <ws> <task_id>` | 单任务调试 rollout（PASS 退 0 / FAIL 退 1） |

## 任务规范（Task Spec）

引擎只吃 `tasks.jsonl`，**不会替你生成任务**。优化 skill 的前提是先有一份合格任务集：

**格式**（每行一个 JSON 对象）：

```json
{"id": "t01", "prompt": "Compute 23 * 17. Reply using the team answer format defined in your skills.", "expected": "product=391"}
```

- `id`：仅 `[A-Za-z0-9._-]`、必须唯一——它直接变成 `runs/` 下的目录名
- `prompt`：自包含，答案由 prompt 唯一确定；"写一段话"类不可判任务不行
- `expected`：**单行**；判分是精确字符串匹配（只归一大小写和空白——没有数值容差、
  没有 regex、没有 LLM judge），别带句尾标点（`391.` 会输给 `391`）

**规模**：≥2 条（否则划不出 val），**建议 ≥20**——val 占 34%，N=10 时 val 只有 3 条，
门控分数一格跳 33%。

**设计原则**（决定演化有没有东西可学）：

1. 想让 skill 有东西可学 → **约定/格式/规则藏进 skill，不藏进 prompt**。prompt 明说
   "格式见你的 skills"，否则强模型 baseline 直接 1.0 → 早停，循环空转（已实测）。
2. **失败必须可归因**：一类任务失败要有共同根因，Maintainer 才能从 trace 沉淀出
   pattern，Proposer 才有据可提。
3. **出题人 ≠ 考生**：agent 写 `expected` 必须用工具算（代码/计算器）核实，不能心算，
   你自己抽查几个——任务本身错了，演化出的 skill 也是错的。

无论谁出题，`init --tasks` 之前必须 `wikiskill tasks check`：**0 failed 才继续**；
WARN（判分风险、N 偏小）逐条看过再决定。

## Procedure

**两条硬性交互规则（不可跳过）**：
- **规则 A — 开场必问**：没有向用户问全"①要什么行为 ②怎么算成功（判分标准）
  ③现有 skill/失败素材在哪 ④输出要不要允许**不确定/弃权**（允许 → 必须
  `--metric selective`；不允许 → 默认 `--metric exact`）"这四点之前，
  **不许出题、不许跑任何命令**。
- **规则 B — 真跑必确认**：hermes 真实 `evolve`（花时间和 token）之前，必须停下来
  向用户说明预估成本并**拿到明确同意**；mock 冒烟除外。

0. **开场采访**（规则 A）：一次性问齐四个问题（目标行为 / 判分标准 / 现有素材 /
   是否允许输出不确定——答案直接决定 `--metric selective` 还是 `exact`），
   用户已给全的可跳问；用户说"直接用默认"时把默认值复述一遍再往下走。
   → completion criterion: 四个问题都有答案（或用户显式授权用默认）。
1. **建/验任务集**（已有合格 tasks.jsonl 则跳过）：按"任务规范"生成任务，expected 用
   工具核实，然后 `tasks check <file>` → completion criterion: 输出 `0 failed`
   （WARN 逐条确认可接受）。
2. `doctor <ws>`（或不带 ws 的全局检查）→ completion criterion: `0 failed`。
   LLM 端点可用性加 `--probe-llm`（GET /models，免费）。
3. 建 workspace：`init <ws> --tasks <file> --backend mock` 先冒烟——
   `evolve <ws> --iters 2`（mock 秒级零成本）→ completion criterion: 打印 iter 表、
   产物落盘。**工具集按任务类型配置**：纯文本任务用 adapter 默认即可；**图片/多模态
   任务必须** `--toolsets terminal,file,vision`（hermes 词汇表；其他 adapter 用自家
   语法，值写进 workspace.json，考生、医生、药剂师全程一致）。不配 = 最小权限
   （无 vision、无 web），考生只能看到文本，图片题会全错。**评分指标**：默认
   `--metric exact`（论文 accuracy）；**任务允许模型弃权/自报不确定时**用
   `--metric selective`（+1 答对、−λ 弃权默认 0.25、−μ 答错默认 1.0，
   `--abstain-penalty/--wrong-penalty` 可调），status 会显示
   coverage/abstain/cond_acc 三元统计，弃权策略由演化自己学（详见 design.md §8.4）。
4. **（规则 B）向用户报告冒烟结果，说明真实 evolve 的预估成本**（实测 ~8 分钟/3 iters、
   ~50 次 agent 调用），**用户明确同意后**再 `init <ws-real> --tasks <file>
   --backend hermes` + `evolve <ws-real> --iters N`（后台跑）→ completion criterion:
   打印 iter 表 + `final R_best=... accepted=N/M`。
5. `status <ws-real>` 核对 → `skills/` 非空、`gating` 有 Accepted 记录。
6. 给用户展示产物：`wiki/skill-impact.md`（提案+diff+分数+结论）、
   `wiki/patterns/*.md`（沉淀的模式页）、`skills/<name>/SKILL.md`（演化出的 skill，
   带 YAML frontmatter，可直接拷进 hermes skills 目录使用）。

## Pitfalls

- **workspace 只能 init 一次**：raw/ 是 append-only（重复写会抛错）。要重跑先删目录，
  或 `init --force`。
- **R_best=1.0 提前退出是正确行为**（Algorithm 1 第 4 行），不是 bug；纯算术 demo
  bench 上强模型会 baseline 直接 1.0 → 什么都不演化（已实测）。
- **别手改 `raw/` 与 `wiki/skill-impact.md`**：前者只增不删，后者仅 harness 可写。
- **rejected 提案不回滚 wiki**，只回滚 skills/——这是论文语义，不是 bug。
- **工具集（toolsets）没配 = 考生只有 terminal+file**：图片任务不加 vision 考生就
  是瞎猜（实测 `ANSWER: NO_VISION`），演化出的 skill 全是垃圾。intake 时先问清
  任务类型，`init --toolsets` 一次配好；`doctor`/`status` 会显示当前值。
- **三值输出（正/负/不确定）必须配 `--metric selective`**：exact 指标下弃权=答错，
  演化只会把不确定越压越死且把错判当弃权罚；selective 下弃权(−0.25)比答错(−1)
  便宜、λ 越小越敢弃权。题目 `expected` 仍全是确定标签——不确定是模型侧行为。
- evolve 有进度输出（每个任务 PASS/FAIL + 耗时），安静模式用 `-q`。
- `evolve`/`run-task` 会先幂等 bootstrap 隔离 profile（`.hermes-home/`），不碰全局
  hermes 配置。

## Verification

- `doctor` 全绿（含目标 ws 的 workspace/layers/tasks 三项）。
- `evolve` 退出码 0 且 iter 表打印完整。
- `status` 的 `gating` 行出现 `Accepted`，`skills/` 列出新 skill。
- mock 后端：`pytest -q`（repo 根，37 passed）可随时回归验证引擎本身。
