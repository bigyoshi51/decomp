from __future__ import annotations


def improvement_reward(
    match_percent: float,
    baseline_percent: float,
    *,
    exact: bool = False,
    compiled: bool = True,
    policy_ok: bool = True,
    collateral_regressions: int = 0,
) -> float:
    """Reward verified improvement while reserving 1.0 for an exact match."""
    if not compiled or not policy_ok:
        return 0.0
    if exact:
        return 1.0
    baseline = min(100.0, max(0.0, baseline_percent))
    candidate = min(100.0, max(0.0, match_percent))
    headroom = max(1e-9, 100.0 - baseline)
    progress = max(0.0, min(1.0, (candidate - baseline) / headroom))
    collateral_penalty = min(0.2, max(0, collateral_regressions) * 0.02)
    return max(0.0, 0.9 * progress - collateral_penalty)
