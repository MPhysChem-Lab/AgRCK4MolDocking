"""PreToolUse guard (Claude Code and Codex). Reads the hook JSON on stdin; exit 2 + stderr blocks the call.

Blocks: (1) code that removes/crops/masks a software watermark or evaluation stamp (license circumvention);
(2) reading the API-key file or printing the key/environment; (3) recursive deletion of studies/results.
Payload shapes: Claude (Bash.command, Write/Edit.file_path+content, Read/Grep.path) and Codex
(exec_command/shell .cmd or .command list, apply_patch .input/.patch). Every string field is scanned.
"""
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]   # this plugin's own sources describe the rule and are exempt
CODE_EXT = re.compile(r"\.(py|pml|sh|bash|js|ts|ipynb|r|m|ps1|bat|cmd)\b", re.I)
WATERMARK = re.compile(r"watermark|marca\s*d.?[aá]gua|no\s+license\s+file|evaluation\s+only|for\s+evaluation", re.I)
EVASION = re.compile(r"remov|crop|recort|apag|eras|inpaint|mask|median|cover|cobr|ocult|hide|clean|limp|paint", re.I)
READERS = (r"cat|less|more|head|tail|type|bat|grep|rg|sed|awk|strings|xxd|od|base64|nl|tac|"
           r"get-content|gc|select-string|sls|import-csv")
ENV_FILE = r"(?<![\w.-])\.env(?![.\w])"
ENV_READ = re.compile(rf"(?:^|[\s;&|(])(?:{READERS})\s+(?:[^|;&]*?){ENV_FILE}", re.I)
PY_OPEN = re.compile(r"(open|read_text|load_dotenv|dotenv_values)\s*\([^)]*['\"][^'\"]*\.env['\"]", re.I)
KEY_ECHO = re.compile(r"(^|[;&|]\s*)(env|printenv|set|export|export\s+-p|declare\s+-x)\s*($|[;&|])|"
                      r"get-childitem\s+env:|\bls\s+env:|\bdir\s+env:|\bgetenv\s*\(|\bdotenv\b[^;&|]*\b(list|get)\b|"
                      r"print\s*\(\s*(dict\()?os\.environ|/proc/[^\s/]+/environ", re.I)
KEY_TEST_OK = re.compile(r"(\[\[?|\btest)\s+-[nz]\s+\"?\$\{?NVIDIA_API_KEY\}?\"?\s*\]?\]?", re.I)
STATE_FILE = re.compile(r"\.(portoes|tentativas|prereg)\b|/\.(p|t)[a-z]*\*", re.I)
WRITE_OP = re.compile(r">|\btee\b|write|open\s*\(|\bsed\s+-i|\brm\b|\bcp\b|\bmv\b|set-content|out-file|unlink|"
                      r"remove|add-content|\bdel\b|copy-item|move-item|truncate|json\.dump|rename|replace", re.I)
REVIEW_FILE = re.compile(r"(^|[/\\])REVISAO\.md$", re.I)
RM_VERB = re.compile(r"(\brm\b[^;&|\n]*\s(-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)\b|"
                     r"\b(remove-item|ri|del|erase|rd|rmdir)\b[^;&|\n]*(-r(ecurse)?\b|/s\b)|"
                     r"\bfind\b[^;&|\n]*-delete\b|\brmtree\s*\()", re.I)


def writes_to(command: str, name: str) -> bool:
    """True when the command modifies a file matching `name` (reads such as `cat x 2>/dev/null` are fine)."""
    c = re.sub(r"\d?>\s*/dev/null|\d>&\d|>\s*/tmp/\S+", "", command)
    verbs = (r"tee|sed\s+-i|rm|cp|mv|set-content|out-file|add-content|remove-item|del|erase|truncate|"
             r"copy-item|move-item|open\s*\(|write_text|write_bytes")
    return bool(re.search(rf">>?\s*['\"]?[^\s;&|]*(?:{name})", c, re.I) or
                re.search(rf"\b(?:{verbs})[^;&|\n]*(?:{name})", c, re.I) or
                re.search(rf"(?:{name})[^;&|\n]{{0,15}}?\b(unlink|write_text|write_bytes|rename|replace)\b", c, re.I))


def block(msg: str) -> None:
    sys.stderr.write("AgRCK guard: " + msg + "\n")
    sys.exit(2)


def strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from strings(v)


def own_source(path: str) -> bool:
    try:
        p = Path(path).resolve()
        return p.is_relative_to(REPO) and p.parent.name in ("hooks", "checks", "tests")
    except (OSError, ValueError):
        return False


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return  # malformed harness payload: nothing to inspect
    tool = str(data.get("tool_name", ""))
    ti = data.get("tool_input", {}) or {}
    if isinstance(ti, str):
        ti = {"input": ti}
    texts = list(strings(ti))
    blob = "\n".join(texts)
    path = str(ti.get("file_path") or ti.get("path") or ti.get("notebook_path") or "")
    cmd = ti.get("command") or ti.get("cmd") or ""
    command = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
    patch_paths = re.findall(r"^\*\*\* (?:Add|Update) File: (.+)$", blob, re.M)

    shell_like = bool(command) or tool.lower() in ("bash", "shell", "exec_command", "powershell", "local_shell")
    is_code = shell_like or bool(CODE_EXT.search(path)) or any(CODE_EXT.search(p) for p in patch_paths)
    targets = [path] + patch_paths if (path or patch_paths) else []
    exempt = bool(targets) and all(own_source(t) for t in targets)
    if is_code and not exempt and WATERMARK.search(blob) and EVASION.search(blob):
        block("remover, recortar ou mascarar marca d'água/aviso de licença é contornar licença e está proibido. "
              "Renderize com PyMOL open-source (agrck doctor) ou mantenha a marca e avise o usuário.")

    if re.search(r"(^|[/\\])\.env$", path.strip()) and tool.lower() not in ("write",):
        block("não leia o arquivo de chaves (.env). Para checar a chave use 'agrck doctor' (não exibe o valor).")
    if tool.lower() == "grep" and (re.search(r"\.env\b(?!\.)", str(ti.get("glob", ""))) or
                                   re.search(r"[/\\]agrck[/\\]?$|\.config[/\\]agrck", path)):
        block("busca no arquivo de chaves (.env) bloqueada. Use 'agrck doctor'.")
    reviewer = "agrck-revisor" in str(data.get("agent_type", "")) or os.environ.get("AGRCK_ROLE") == "revisor"
    if not reviewer and (any(REVIEW_FILE.search(t.strip()) for t in targets if tool.lower() != "read") or
                         (shell_like and writes_to(command, r"REVISAO\.md"))):
        block("relatorio/REVISAO.md só pode ser escrito pelo revisor independente (subagente agrck-revisor; no "
              "Codex, sessão com AGRCK_ROLE=revisor) ou pelo próprio usuário fora do agente.")
    if any(STATE_FILE.search(t) for t in targets if tool.lower() != "read") or \
            (shell_like and writes_to(command, STATE_FILE.pattern)):
        block("o estado dos portões/tentativas/pré-registro só é escrito pelo agrck (agrck check / attempt). "
              "Não edite .portoes.json, .tentativas.json nem .prereg.json.")
    if shell_like:
        scan = command or blob
        if "NVIDIA_API_KEY" in KEY_TEST_OK.sub("", scan).upper() or ENV_READ.search(scan) or PY_OPEN.search(scan) \
                or KEY_ECHO.search(scan):
            block("comando exporia a NVIDIA_API_KEY ou o ambiente. Use 'agrck doctor' para verificar a configuração.")
        for seg in re.split(r"[;&|\n]+", scan):
            if RM_VERB.search(seg) and re.search(r"estudos|results", seg, re.I):
                block("exclusão recursiva de estudos/resultados: peça confirmação explícita ao usuário e "
                      "faça-a manualmente se ele aprovar.")


if __name__ == "__main__":
    main()
