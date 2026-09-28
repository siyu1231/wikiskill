"""Algorithm 1 evolution loop: rollout → maintain → propose → gate → audit.

TODO(P1): strict-improvement gating, skills-only rollback, skill-impact.md audit trail,
early stop at R_best == 1.0. Adapted in part from kenhuangus/wikiskill (MIT).
"""
