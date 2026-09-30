"""Algorithm 1 evolution loop (paper §3.2): rollout -> maintain -> propose -> gate -> audit.

Gating (§3.2.4): accept iff R(T_val,k) > R_best (strict); otherwise revert skills only.
The wiki is NEVER rolled back. skill-impact.md is written exclusively by this harness.
Adapted in part from kenhuangus/wikiskill (MIT).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .agents import SkillProposer, WikiMaintainer, stratified_sample
from .harness import Task
from .metrics import score, select_stats
from .skills import Proposal, SkillSet
from .workspace import Workspace

# rollout(tasks, skills_context, iteration, split) -> list[trace dict]
RolloutFn = Callable[[list[Task], str, int, str], list[dict]]


@dataclass
class IterationReport:
    k: int
    proposal: Proposal | None
    diff: str | None
    val_score: float
    r_best: float
    accepted: bool
    train_score: float = 0.0
    patches_applied: int = 0
    notes: str = ""


@dataclass
class EvolutionResult:
    r_best: float
    baseline: float
    iterations: list[IterationReport] = field(default_factory=list)

    @property
    def accepted_count(self) -> int:
        return sum(1 for i in self.iterations if i.accepted)


class Orchestrator:
    def __init__(self, ws: Workspace, maintainer: WikiMaintainer, proposer: SkillProposer,
                 rollout: RolloutFn, metric: dict | None = None):
        self.ws = ws
        self.skills = SkillSet(ws.skills_dir)
        self.maintainer = maintainer
        self.proposer = proposer
        self.rollout = rollout
        # None / {"name":"exact"} -> paper metric; {"name":"selective",...} -> abstention-aware
        self.metric = metric

    def _score(self, traces: list[dict]) -> float:
        return score(traces, self.metric)

    def _stats_extra(self, traces: list[dict]) -> tuple[str, str]:
        """(audit multiline, log compact) tri-metric lines; empty under exact."""
        if (self.metric or {}).get("name", "exact") != "selective":
            return "", ""
        st = select_stats(traces)
        audit = (f"\n- selective: correct={st['correct']} abstain={st['abstain']} "
                 f"wrong={st['wrong']} | coverage={st['coverage']:.3f} "
                 f"abstain_rate={st['abstain_rate']:.3f} cond_acc={st['cond_acc']:.3f}")
        log = (f"  correct={st['correct']} abstain={st['abstain']} wrong={st['wrong']}"
               f" coverage={st['coverage']:.2f} cond_acc={st['cond_acc']:.2f}")
        return audit, log

    def _run_split(self, tasks: list[Task], iteration: int, split: str) -> list[dict]:
        ctx = self.skills.full_context()
        traces = self.rollout(tasks, ctx, iteration, split)
        for t in traces:
            self.ws.save_trace(iteration, str(t.get("task_id", "unknown")), split, t)
        return traces

    def evolve(self, train: list[Task], val: list[Task], max_iters: int = 10) -> EvolutionResult:
        # line 2: baseline validation with empty skill set
        baseline_traces = self._run_split(val, 0, "val")
        r_best = self._score(baseline_traces)
        result = EvolutionResult(r_best=r_best, baseline=r_best)

        for k in range(1, max_iters + 1):
            if r_best >= 1.0:                       # line 4: early stop
                break
            # line 7-8: inference on D_train + stratified sampling
            train_traces = self._run_split(train, k, "train")
            sample = stratified_sample(train_traces)
            # line 9: wiki maintenance (wiki monotonic — applies regardless of gating)
            patches = self.maintainer.consolidate(sample)
            self.ws.append_log(f"## Iteration {k}\n- traces: {len(train_traces)} "
                               f"(sampled {len(sample)}), wiki patches: {patches}")
            # line 10-11: skill proposal (atomic) + apply
            proposal = self.proposer.propose(train_traces, k)
            if proposal is None:
                self.ws.append_skill_impact(f"### Iteration {k}\n- outcome: NoProposal")
                result.iterations.append(IterationReport(
                    k=k, proposal=None, diff=None, val_score=r_best, r_best=r_best,
                    accepted=False, train_score=self._score(train_traces),
                    patches_applied=patches, notes="proposer returned no proposal"))
                continue
            snap = self.skills.snapshot()
            try:
                diff = self.skills.apply(proposal)
            except Exception as e:                  # invalid proposal -> no state change
                self.ws.append_skill_impact(
                    f"### Iteration {k}\n{proposal.to_markdown()}\n"
                    f"- outcome: Rejected (invalid proposal: {e})")
                result.iterations.append(IterationReport(
                    k=k, proposal=proposal, diff=None, val_score=r_best, r_best=r_best,
                    accepted=False, train_score=self._score(train_traces),
                    patches_applied=patches, notes=f"invalid: {e}"))
                continue
            # line 12: validation with candidate skills
            val_traces = self._run_split(val, k, "val")
            val_score = self._score(val_traces)
            # line 13-17: strict-improvement gate, skills-only rollback
            accepted = val_score > r_best
            if accepted:
                r_best = val_score
            else:
                self.skills.restore(snap)
            # line 18: audit trail (harness writes; wiki never rolled back)
            audit_extra, log_extra = self._stats_extra(val_traces)
            self.ws.append_skill_impact(
                self._impact_entry(k, proposal, diff, val_score, accepted, r_best, audit_extra))
            self.ws.append_log(f"- validation: {val_score:.3f} "
                               f"({'Accepted' if accepted else 'Rejected'}), "
                               f"R_best={r_best:.3f}{log_extra}")
            result.iterations.append(IterationReport(
                k=k, proposal=proposal, diff=diff, val_score=val_score, r_best=r_best,
                accepted=accepted, train_score=self._score(train_traces),
                patches_applied=patches))
        result.r_best = r_best
        return result

    @staticmethod
    def _impact_entry(k: int, p: Proposal, diff: str, score: float, accepted: bool,
                      r_best: float, extra: str = "") -> str:
        return (
            f"### Iteration {k}\n"
            f"{p.to_markdown()}\n"
            f"```diff\n{diff.rstrip()}\n```\n"
            f"- val_score: {score:.4f}{extra}\n"
            f"- R_best after gate: {r_best:.4f}\n"
            f"- outcome: {'Accepted' if accepted else 'Rejected'}"
        )
