from app.models.reverse_rule import CandidateRuleForDB


def merge_candidate_rules(rules: list[CandidateRuleForDB]) -> list[CandidateRuleForDB]:
    merged: dict[tuple[str, str, str], CandidateRuleForDB] = {}
    for rule in rules:
        key = (rule.review_module, rule.risk_name, rule.check_point)
        if key not in merged:
            merged[key] = rule
            continue
        existing = merged[key]
        seen = {
            (trace.pair_id, trace.evidence_before, trace.evidence_after)
            for trace in existing.traces
        }
        existing.traces.extend(
            trace
            for trace in rule.traces
            if (trace.pair_id, trace.evidence_before, trace.evidence_after) not in seen
        )
    return list(merged.values())
