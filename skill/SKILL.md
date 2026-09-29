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
| `wikiskill init <ws> [--backend mock\|hermes] [--tasks f.jsonl] [--seed N]` | 建 workspace + 划分 train/val |
| `wikiskill evolve <ws> --iters N [-q]` | 跑 Algorithm 1 演化循环 |
| `wikiskill status <ws>` | 三层状态 + 门控历史 + R_best |
| `wikiskill run-task <ws> <task_id>` | 单任务调试 rollout（PASS 退 0 / FAIL 退 1） |

## Procedure

1. `doctor <ws>`（或不带 ws 的全局检查）→ completion criterion: `0 failed`。
   LLM 端点可用性加 `--probe-llm`（GET /models，免费）。
2. 没有 workspace 就 `init`（默认 12 个 demo 任务，train 8 / val 4）→ 输出含
   `tasks : 12 total -> train 8 / val 4`。
3. `evolve <ws> --iters 3`（后台跑）→ completion criterion: 打印 iter 表 +
   `final R_best=... accepted=N/M`。
4. `status <ws>` 核对 → `skills/` 非空、`gating` 有 Accepted 记录。
5. 给用户展示产物：`wiki/skill-impact.md`（提案+diff+分数+结论）、
   `wiki/patterns/*.md`（沉淀的模式页）、`skills/<name>/SKILL.md`（演化出的 skill，
   带 YAML frontmatter，可直接拷进 hermes skills 目录使用）。

## Pitfalls

- **workspace 只能 init 一次**：raw/ 是 append-only（重复写会抛错）。要重跑先删目录，
  或 `init --force`。
- **R_best=1.0 提前退出是正确行为**（Algorithm 1 第 4 行），不是 bug；纯算术 demo
  bench 上强模型会 baseline 直接 1.0 → 什么都不演化（已实测）。
- **别手改 `raw/` 与 `wiki/skill-impact.md`**：前者只增不删，后者仅 harness 可写。
- **rejected 提案不回滚 wiki**，只回滚 skills/——这是论文语义，不是 bug。
- evolve 有进度输出（每个任务 PASS/FAIL + 耗时），安静模式用 `-q`。
- `evolve`/`run-task` 会先幂等 bootstrap 隔离 profile（`.hermes-home/`），不碰全局
  hermes 配置。

## Verification

- `doctor` 全绿（含目标 ws 的 workspace/layers/tasks 三项）。
- `evolve` 退出码 0 且 iter 表打印完整。
- `status` 的 `gating` 行出现 `Accepted`，`skills/` 列出新 skill。
- mock 后端：`pytest -q`（repo 根，37 passed）可随时回归验证引擎本身。
