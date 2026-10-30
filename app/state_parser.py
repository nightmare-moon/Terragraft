"""Read-only inventory extracted from Terraform's *raw* v4 state snapshot.

Do not use this representation to reconstruct Terraform state: raw state contains
provider-private fields, identity information and sensitive attributes.
"""
from __future__ import annotations

import json
from typing import Any


def _instance_suffix(instance: dict[str, Any]) -> str:
    key = instance.get('index_key')
    if isinstance(key, bool):
        return f'[{json.dumps(key)}]'
    if isinstance(key, int):
        return f'[{key}]'
    if isinstance(key, str):
        return f'[{json.dumps(key, ensure_ascii=False)}]'
    return ''


def extract_graph(state: dict[str, Any]) -> tuple[list[dict[str, str]], list[tuple[str, str]]]:
    """Return deduplicated instance nodes and direct (dependent, dependency) edges.

    The inventory is informational: Terraform's actual execution graph depends
    on HCL, providers, data sources, lifecycle flags and plan-time evaluation.
    """
    nodes: dict[str, dict[str, str]] = {}
    edges: set[tuple[str, str]] = set()
    for block in state.get('resources', []) or []:
        if not isinstance(block, dict):
            continue
        module = str(block.get('module', ''))
        mode = str(block.get('mode', 'managed'))
        type_name = str(block.get('type', ''))
        name = str(block.get('name', ''))
        if not type_name or not name:
            continue
        prefix = f'{module}.' if module else ''
        if mode == 'data':
            prefix += 'data.'
        block_address = f'{prefix}{type_name}.{name}'
        for instance in block.get('instances', []) or []:
            if not isinstance(instance, dict):
                continue
            address = block_address + _instance_suffix(instance)
            nodes[address] = {
                'address': address,
                'provider': str(block.get('provider', '')),
                'resource_type': type_name,
                'mode': mode,
            }
            for target in instance.get('dependencies', []) or []:
                if isinstance(target, str) and target != address:
                    edges.add((address, target))
    return sorted(nodes.values(), key=lambda n: n['address']), sorted(edges)
