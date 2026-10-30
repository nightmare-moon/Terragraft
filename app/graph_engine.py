"""Pure dependency and OCC helpers, intentionally distinct from Terraform state."""
from __future__ import annotations


def impacted_resources(changed: set[str], edges: list[tuple[str, str]], include_dependents: bool = True) -> set[str]:
    """Conservative transitive reverse closure; (dependent, dependency)."""
    result = set(changed)
    if include_dependents:
        frontier = list(changed)
        reverse: dict[str, set[str]] = {}
        for source, target in edges:
            reverse.setdefault(target, set()).add(source)
        while frontier:
            for dependent in reverse.get(frontier.pop(), ()):
                if dependent not in result:
                    result.add(dependent)
                    frontier.append(dependent)
    return result


def conflicting_versions(expected: dict[str, int], current: dict[str, int]) -> dict[str, dict[str, int]]:
    return {key: {'expected': version, 'current': current.get(key, 0)}
            for key, version in expected.items() if version != current.get(key, 0)}


def valid_resource_address(address: str) -> bool:
    return bool(address and 0 < len(address) <= 512 and '\x00' not in address and address == address.strip())


def prerequisite_resources(changed: set[str], edges: list[tuple[str,str]]) -> set[str]:
    """Transitive dependencies that a scoped write may have read."""
    direct: dict[str, set[str]] = {}
    for dependent, dependency in edges:
        direct.setdefault(dependent, set()).add(dependency)
    visited = set(changed)
    stack = list(changed)
    while stack:
        for dependency in direct.get(stack.pop(), ()):
            if dependency not in visited:
                visited.add(dependency)
                stack.append(dependency)
    return visited - changed
