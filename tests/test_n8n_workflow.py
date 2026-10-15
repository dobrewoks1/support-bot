import importlib.util
import json
from pathlib import Path

from tests.conftest import ROOT


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_workflow", ROOT / "n8n" / "build_workflow.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_workflow_builder_produces_consistent_graph() -> None:
    workflow = _load_builder().build()
    names = [node["name"] for node in workflow["nodes"]]
    assert len(names) == len(set(names)), "имена узлов должны быть уникальными"
    for source, outputs in workflow["connections"].items():
        assert source in names, source
        for kind, branches in outputs.items():
            for branch in branches:
                for link in branch:
                    assert link["node"] in names, link
                    assert link["type"] == kind
    types = {node["type"] for node in workflow["nodes"]}
    assert {"n8n-nodes-base.telegramTrigger", "n8n-nodes-base.telegram", "n8n-nodes-base.code",
            "@n8n/n8n-nodes-langchain.chainLlm", "@n8n/n8n-nodes-langchain.lmChatAnthropic"} <= types
    code = next(n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.code")["parameters"]["jsCode"]
    assert "Сколько стоит замена масла?" in code, "база знаний должна быть встроена в узел Code"


def test_committed_workflow_json_is_up_to_date() -> None:
    committed = json.loads((ROOT / "n8n" / "support-bot.workflow.json").read_text(encoding="utf-8"))
    assert committed == _load_builder().build(), "запустите python n8n/build_workflow.py после правки базы знаний"
