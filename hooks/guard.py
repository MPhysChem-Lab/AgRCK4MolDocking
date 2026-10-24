"""PreToolUse guard (Claude Code and Codex). Reads the hook JSON on stdin; exit 2 + stderr blocks the call.

Blocks: (1) code that removes/crops/masks a software watermark or evaluation stamp (license circumvention);
(2) reading the API-key file or printing the key/environment; (3) recursive deletion of studies/results.
Payload shapes: Claude (Bash.command, Write/Edit.file_path+content, Read/Grep.path) and Codex
(exec_command/shell .cmd or .command list, apply_patch .input/.patch). Every string field is scanned.
"""
import json
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
KEY_ECHO = re.compile(r"NVIDIA_API_KEY[^\n]*\b(echo|print|write-output|write-host)\b|"
                      r"\b(echo|printf|print|write-output|write-host|out-host)\b[^\n]*(\$\{?|\$env:|environ)[^\n]*NVIDIA_API_KEY|"
                      r"(^|[;&|]\s*)(env|printenv|set|export\s+-p)\s*($|[;&|])|get-childitem\s+env:|\bls\s+env:|dir\s+env:", re.I)
RM_STUDY = re.compile(r"(\brm\s+(-[a-zA-Z]*r[a-zA-Z]*|--recursive)\b|remove-item\b[^;&|]*-r(ecurse)?\b|\brmtree\s*\(|"
                      r"\brd\s+/s|\brmdir\s+/s)[^;&|]*(estudos|results)", re.I)


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
    if shell_like or tool.lower() in ("grep",):
        scan = command or blob
        if ENV_READ.search(scan) or PY_OPEN.search(scan) or KEY_ECHO.search(scan):
            block("comando exporia a NVIDIA_API_KEY ou o ambiente. Use 'agrck doctor' para verificar a configuração.")
        if RM_STUDY.search(scan):
            block("exclusão recursiva de estudos/resultados: peça confirmação explícita ao usuário e "
                  "faça-a manualmente se ele aprovar.")


if __name__ == "__main__":
    main()
