"""
Shared test helpers for Stream 2 unit tests. Not a test file itself
(leading underscore keeps unittest discovery from collecting it).
"""

import os
import sys
import importlib.util

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
COMMON_LAYER_DIR = os.path.join(REPO_ROOT, "src", "shared", "common-layer")

os.environ.setdefault("AWS_DEFAULT_REGION", "eu-central-1")

if COMMON_LAYER_DIR not in sys.path:
    sys.path.insert(0, COMMON_LAYER_DIR)


def load_handler_module(module_name, handler_dir):
    """
    Load a stream2 handler.py under a unique module name.

    Every stream's Lambda entry point is literally named handler.py, so a
    plain `import handler` would collide across test files via sys.modules —
    this loads each one under a distinct name instead.
    """
    path = os.path.join(REPO_ROOT, "src", "stream2", handler_dir, "handler.py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class FakeTable:
    """Minimal in-memory stand-in for a boto3 DynamoDB Table resource."""

    def __init__(self, key_fields):
        self.key_fields = key_fields  # e.g. ("client_id",) or ("client_type", "rule_key")
        self.items = {}

    def _key_tuple(self, key_or_item):
        return tuple(key_or_item[f] for f in self.key_fields)

    def get_item(self, Key):
        item = self.items.get(self._key_tuple(Key))
        return {"Item": item} if item is not None else {}

    def put_item(self, Item):
        self.items[self._key_tuple(Item)] = Item

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ExpressionAttributeNames=None):
        item = self.items.setdefault(self._key_tuple(Key), dict(Key))
        if "risk_flags" in UpdateExpression:
            item["risk_flags"] = item.get("risk_flags", []) + ExpressionAttributeValues[":flag"]
        if ":ts" in ExpressionAttributeValues:
            item["updated_at"] = ExpressionAttributeValues[":ts"]
        return {"Attributes": item}
