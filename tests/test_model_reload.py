from __future__ import annotations

import importlib
import warnings


def test_sqlmodel_modules_can_be_reloaded_without_table_conflicts():
    module_names = [
        "models.order",
        "models.user",
        "models.product",
        "models.audit_log",
        "models.warehouse_event",
    ]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for module_name in module_names:
            module = importlib.import_module(module_name)
            importlib.reload(module)
