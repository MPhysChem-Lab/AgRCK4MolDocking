"""Consistency of the agent package: lessons -> tests, docs -> CLI, agents -> model/effort, manifests."""
import json
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
TEST_SRC = "\n".join(p.read_text(encoding="utf-8") for p in (REPO / "tests").glob("test_*.py"))


def test_every_lesson_names_existing_tests():
    rows = [l for l in (REPO / "templates/memoria/LICOES.md").read_text(encoding="utf-8").splitlines()
            if re.match(r"\|\s*\d+\s*\|", l)]
    assert len(rows) >= 14
    for row in rows:
        names = re.findall(r"`(test_\w+)`", row.split("|")[-2])
        assert names, f"lição sem teste: {row[:60]}"
        for n in names:
            assert re.search(rf"def {n}\(", TEST_SRC), f"teste inexistente: {n}"


def test_docs_only_mention_existing_agrck_commands():
    src = (REPO / "pipeline/agrck.py").read_text(encoding="utf-8")
    cmds = set(re.findall(r'add_parser\("(\w+)"', src))
    texts = [REPO / "AGENTS.md", *REPO.glob("skills/*/SKILL.md"), *REPO.glob("agents/*.md"), *REPO.glob("docs/*.md")]
    for p in texts:
        for c in re.findall(r"`agrck (\w+)", p.read_text(encoding="utf-8")):
            assert c in cmds, f"{p.name}: 'agrck {c}' não existe"


def test_context_stays_small():
    assert len((REPO / "AGENTS.md").read_text(encoding="utf-8").splitlines()) <= 35
    assert (REPO / "templates/workspace/AGENTS.md").read_text(encoding="utf-8") == \
        (REPO / "AGENTS.md").read_text(encoding="utf-8")
    assert not (REPO / "CLAUDE.md").exists()        # plugin root CLAUDE.md is not loaded and fails strict validation


def test_agents_pin_model_and_effort_as_documented():
    table = (REPO / "docs/ORQUESTRACAO.md").read_text(encoding="utf-8")
    for p in REPO.glob("agents/*.md"):
        fm = yaml.safe_load(p.read_text(encoding="utf-8").split("---")[1])
        assert fm.get("model") and fm.get("effort"), p.name
        assert re.search(rf"`{fm['name']}`\s*\|\s*{fm['model']}\s*\|\s*{fm['effort']}", table), p.name


def test_manifests_agree():
    names, versions = set(), set()
    for f in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json", "plugin.json"):
        m = json.loads((REPO / f).read_text(encoding="utf-8"))
        names.add(m["name"])
        versions.add(m["version"])
    assert len(names) == 1 and len(versions) == 1
    mk = json.loads((REPO / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
    ck = json.loads((REPO / ".agents/plugins/marketplace.json").read_text(encoding="utf-8"))
    assert mk["plugins"][0]["name"] in names and ck["plugins"][0]["name"] in names
    hooks = json.loads((REPO / "hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]
    assert "Grep" in hooks["PreToolUse"][0]["matcher"]
