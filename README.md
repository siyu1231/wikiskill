# wikiskill

Python implementation of **WikiSkill: Compiling Agent Experience into Persistent Knowledge for Skill Evolution** ([arXiv:2608.27454](https://arxiv.org/abs/2608.27454), Tang et al., Google Research + Virginia Tech, 2026-08-27).

Google Research has **not** released official code for this paper. This project is an independent reimplementation whose goal differs from the two existing community ports:

- **Agent-agnostic evolution loop**: the WikiSkill loop (Algorithm 1) can drive multiple agent backends — Hermes Agent, Claude Code, Codex CLI, pi-agent — through a single backend protocol.
- **Paper fidelity where it matters**: full skill injection into the inference prompt, immutable raw layer, skills-only rollback (wiki never rolls back), stratified trace sampling, paired-bootstrap significance testing.

## Provenance

| Source | What we take | License |
|---|---|---|
| [kenhuangus/wikiskill](https://github.com/kenhuangus/wikiskill) (vendored in `vendor/kenhuangus/`) | workspace/orchestrator/gating/prompts/metrics — the most faithful Algorithm 1 implementation found | MIT |
| [ashutoshsinghpr7/wikiskill](https://github.com/ashutoshsinghpr7/wikiskill) (vendored in `vendor/ashutosh/`) | multi-backend protocol, adapters, transcript normalization, isolation | MIT |
| Paper itself | method, algorithm, agent prompts (Appendix E) | CC BY 4.0 |

See `THIRD_PARTY_NOTICES.md` and `design.md`.

## Status

Early development. See `design.md` for the architecture and the porting plan.

## Citation

```bibtex
@article{tang2026wikiskill,
  title   = {WikiSkill: Compiling Agent Experience into Persistent Knowledge for Skill Evolution},
  author  = {Tang, Liyan and Rashtchian, Cyrus and Ferng, Chun-Sung and Tomkins, Andrew and Juan, Da-Cheng and Vu, Tu},
  journal = {arXiv preprint arXiv:2608.27454},
  year    = {2026},
  note    = {Google Research}
}
```
