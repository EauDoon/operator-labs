"""Value-free inspection of declared synthetic privacy checks and coverage."""
from .contract import Contract
from .report import Violation, build_report, ensure_object_values_absent, ensure_values_absent


def _privacy_checked(contract: Contract, report):
    values = tuple(canary.value for canary in contract.canaries)
    ensure_object_values_absent(report, values)
    ensure_values_absent(report, values)
    return report


def inspect_contract(contract: Contract):
    """Inventory effective checks and find directly contradictory retention requirements."""
    conflicts = []
    for index, field in enumerate(contract.required_retained_fields, 1):
        if field.key in contract.forbidden_attribute_keys or any(
            field.key.startswith(prefix) for prefix in contract.forbidden_attribute_key_prefixes
        ):
            conflicts.append(f"required-{index:04d}")
    violations = [Violation("TC010", "", "contract requires a field forbidden by its attribute rules")] if conflicts else []
    report = build_report(contract.contract_version, "regression" if conflicts else "pass", violations,
                          mode="inspect-contract", redacted_values=tuple(canary.value for canary in contract.canaries))
    report["inspection"] = {"semantic_conventions_version": contract.semantic_conventions_version,
        "canary_count": len(contract.canaries), "forbidden_key_count": len(contract.forbidden_attribute_keys),
        "forbidden_key_prefix_count": len(contract.forbidden_attribute_key_prefixes),
        "forbidden_path_prefix_count": len(contract.forbidden_path_prefixes),
        "required_fields": [{"id": f"required-{index:04d}", "scope": field.scope}
                            for index, field in enumerate(contract.required_retained_fields, 1)],
        "retention_conflicts": conflicts,
        "limits": {"max_input_bytes": contract.max_input_bytes, "max_nesting": contract.max_nesting,
                   "max_batch_files": contract.max_batch_files}}
    return _privacy_checked(contract, report)
