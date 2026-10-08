# wikiskill

[English](README.md) | 简体中文

**WikiSkill 论文的 Python 实现**——《WikiSkill: Compiling Agent Experience into Persistent
Knowledge for Skill Evolution》（[arXiv:2608.27454](https://arxiv.org/abs/2608.27454)，
Tang et al., Google Research + Virginia Tech, 2026-08-27）。

Google Research **未**发布该论文的官方代码。本项目是独立复现，与两个已有的社区移植版
定位不同，主打两点：

- **Agent 无关的演化循环**：WikiSkill 循环（Algorithm 1）通过统一的 backend 协议驱动多种
  CLI agent——Hermes Agent、Claude Code、Codex CLI、pi-agent——核心零 agent 依赖。
- **关键处忠于论文**：推理提示词全量注入 skill、raw 层不可变、仅回滚 skills/（wiki 永不
  回滚）、分层轨迹采样（≤5 错 + ≤3 对）、留出集 val 门控、严格 `>` 接受准则。

## 特性

| 能力 | 说明 |
|---|---|
| 多后端 | `backends/` 协议化适配器：`hermes`（真实 agent，隔离 HERMES_HOME）与 `mock`（零成本离线）；claude/codex/pi 计划中 |
| 三层 workspace | `raw/` 只增不删（重复写抛错）· `wiki/` 持久知识（永不回滚）· `skills/` 活跃状态（唯一可回滚层） |
| 统一 runner | 三个角色（考生 / Wiki Maintainer / Skill Proposer）默认全走 agent CLI（复用 agent 自身凭证，零额外配置）；`--runner direct` 可选直连 OpenAI 兼容端点 |
| 并发 rollout | `--workers N` 线程池并行调用，traces 恒按题序收集；实测 8 路并发跑 7828 次真实调用无损坏 |
| 两种评分 | `--metric exact`（论文 exact-match accuracy，默认）；`--metric selective`（弃权感知：`R = (correct − λ·abstain − μ·wrong)/N`，默认 λ=0.25、μ=1，让演化学会"拿不准时自报不确定"） |
| 工具集配置 | `--toolsets <adapter 词汇表>`（如 hermes: `terminal,file,vision`）持久化到 workspace，考生/医生/药剂师全程一致；默认最小权限 |
| 自检与质检 | `wikiskill doctor`（环境/workspace/LLM 端点探活）、`wikiskill tasks check`（任务集格式与判分风险检查） |
| 代码执法 | 门控、回滚、审计、采样预算全部由代码强制并被测试锁定——不靠 prose 嘱托 |

## 安装

```bash
git clone https://github.com/siyu1231/wikiskill.git
cd wikiskill
python -m venv .venv
.venv/Scripts/pip install -e .        # Windows；Unix 用 .venv/bin/pip
wikiskill doctor                      # 环境自检（加 --probe-llm 探测 LLM 端点）
```

## 快速开始

```bash
# 1) 冒烟（mock 后端，秒级零成本）
wikiskill init ws --backend mock
wikiskill evolve ws --iters 2
wikiskill status ws

# 2) 真实 agent 演化（hermes；图片任务 + 弃权评分 + 8 并发）
wikiskill init ws-real --tasks tasks.jsonl --backend hermes \
    --toolsets terminal,file,vision --metric selective --workers 8
wikiskill evolve ws-real --iters 5      # 真跑前会报告预估成本
wikiskill status ws-real
```

产物：`skills/<name>/SKILL.md`（演化出的可直接使用的 skill）、`wiki/patterns/`（根因页）、
`wiki/skill-impact.md`（每轮提案 + diff + 分数 + 接受/拒绝的完整审计）、`raw/iter-*/`
（全部判分轨迹）、`runs/`（每次 agent 调用的原始输入输出）。

## 三层 workspace 布局

```
ws/
├── workspace.json    配置（backend / toolsets / workers / metric / seed）
├── tasks.jsonl       题目（init 后不再改）
├── raw/              判分档案：只增不删，split-题号.json（不可变层）
├── wiki/             patterns/ · index.md · logs.md · skill-impact.md（持久层，永不回滚）
├── skills/           当前生效 skill + PURPOSE.md（活跃层，门控失败即回滚）
├── runs/             每次调用的 query.txt / stdout.txt / session 导出
└── .hermes-home/     隔离的 agent profile（复制凭证、清空会话与记忆）
```

## 论文循环（Algorithm 1）

```
baseline(val, 空 skill) → 每轮：train rollout → 分层采样 → Wiki Maintainer（诊断写 wiki）
→ Skill Proposer（一个原子提案）→ val 门控（严格 > 才接受，否则仅回滚 skills/）
→ 审计入 skill-impact.md → R_best=1.0 早停
```

评分与门控、回滚、审计语义由 `src/wikiskill/` 代码强制，`design.md` §8 记录全部设计决策
（含 selective metric 相对论文的偏离点）。

## 项目来源

| 来源 | 采用内容 | 许可 |
|---|---|---|
| [kenhuangus/wikiskill](https://github.com/kenhuangus/wikiskill)（vendored 于 `vendor/kenhuangus/`） | workspace / orchestrator / gating / prompts / metrics——所见最忠于 Algorithm 1 的实现 | MIT |
| [ashutoshsinghpr7/wikiskill](https://github.com/ashutoshsinghpr7/wikiskill)（vendored 于 `vendor/ashutosh/`） | 多后端协议、适配器、transcript 归一化与隔离 | MIT |
| 论文本身 | 方法、算法、agent 提示词（附录 E） | CC BY 4.0 |

详见 `THIRD_PARTY_NOTICES.md` 与 `design.md`。

## 状态

早期开发中。架构与移植计划见 `design.md`。已实测：mock 全流程、真实 hermes 单题/多轮、
8 路并发 30 轮长跑（7828 次调用，baseline 0.66 → R_best 0.95，3 次接受 / 27 次拒绝）。

## 许可

MIT，见 [LICENSE](LICENSE)。

## 引用

```bibtex
@article{tang2026wikiskill,
  title   = {WikiSkill: Compiling Agent Experience into Persistent Knowledge for Skill Evolution},
  author  = {Tang, Liyan and Rashtchian, Cyrus and Ferng, Chun-Sung and Tomkins, Andrew and Juan, Da-Cheng and Vu, Tu},
  journal = {arXiv preprint arXiv:2608.27454},
  year    = {2026},
  note    = {Google Research}
}
```
