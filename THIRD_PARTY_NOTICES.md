# Third-Party Notices

This project is an independent reimplementation of *WikiSkill* (arXiv:2608.27454). It is **not** an official Google product.

## wiki (paper)

- **WikiSkill: Compiling Agent Experience into Persistent Knowledge for Skill Evolution**
  Liyan Tang, Cyrus Rashtchian, Chun-Sung Ferng, Andrew Tomkins, Da-Cheng Juan, Tu Vu — Google Research (and Virginia Tech)
- arXiv:2608.27454v1 [cs.AI], 27 Aug 2026 — licensed under **CC BY 4.0**
- Method, Algorithm 1, three-layer architecture, and agent system prompts (Appendix E) are credited to the paper authors; prompt texts in `src/wikiskill/prompts.py` are condensed adaptations.

## vendor/kenhuangus/wikiskill

- https://github.com/kenhuangus/wikiskill — **MIT License** (see `vendor/kenhuangus/LICENSE`)
- Portions of `workspace`, `orchestrator` (gating/rollback/audit), `metrics` (paired bootstrap), and `prompts` are adapted from this implementation.

## vendor/ashutosh/wikiskill

- https://github.com/ashutoshsinghpr7/wikiskill — **MIT License** (see `vendor/ashutosh/LICENSE`)
- Portions of the backend protocol, backend adapters, workspace isolation, and transcript normalization are adapted from this implementation.

## Karpathy LLM Wiki

The paper (and this project) is inspired by Andrej Karpathy's 2026 "LLM Wiki" perspective on compiling experience into persistent, compounding knowledge.
