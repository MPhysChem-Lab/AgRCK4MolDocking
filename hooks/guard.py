"""PreToolUse guard (Claude Code and Codex). Reads the hook JSON on stdin; exit 2 + stderr blocks the call.

Blocks: (1) code that removes/crops/masks a software watermark or evaluation stamp (license circumvention);
(2) reading the API-key file or echoing the key; (3) recursive deletion of studies/results without asking.
"""
import json
import re
import sys

CODE_EXT = re.compile(r"\.(py|pml|sh|bash|js|ts|ipynb|r|m|ps1|bat)\b", re.I)
WATERMARK = re.compile(r"watermark|marca\s*d.?[aá]gua|no\s+license\s+file|evaluation\s+only|for\s+evaluation", re.I)
EVASION = re.compile(r"remov|crop|recort|apag|eras|inpaint|mask|median|cover|cobr|ocult|hide|clean|limp|paint", re.I)
ENV_READ = re.compile(r"(cat|less|more|head|tail|type|bat|grep|sed|awk|strings|xxd|od|base64)\s+"
                      r"(?:[^|;&]*[\s/\\'\"])?\.env(?![.\w])")
KEY_ECHO = re.compile(r"(echo|printf|print)[^\n]*\$\{?NVIDIA_API_KEY|printenv\s+NVIDIA_API_KEY")
RM_STUDY = re.compile(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*\s[^;&|]*(estudos|results)", re.I)


def block(msg: str) -> None:
    sys.stderr.write("AgRCK guard: " + msg + "\n")
    sys.exit(2)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    tool = str(data.get("tool_name", ""))
    ti = data.get("tool_input", {}) or {}
    blob = json.dumps(ti, ensure_ascii=False)
    path = str(ti.get("file_path") or ti.get("path") or ti.get("notebook_path") or "")
    command = str(ti.get("command") or "")

    is_code = bool(CODE_EXT.search(path)) or tool in ("Bash", "shell", "exec_command", "PowerShell") or \
        (tool == "apply_patch" and CODE_EXT.search(blob))
    guard_sources = re.search(r"(guard|figure_check|report_check|test_guards)\.py$", path)  # they describe the rule
    if is_code and not guard_sources and WATERMARK.search(blob) and EVASION.search(blob):
        block("remover, recortar ou mascarar marca d'água/aviso de licença é contornar licença e está proibido. "
              "Renderize com PyMOL open-source (agrck doctor) ou mantenha a marca e avise o usuário.")

    if tool in ("Read", "read_file") and re.search(r"(^|[/\\])\.env$", path):
        block("não leia o arquivo de chaves (.env). Para checar a chave use 'agrck doctor' (não exibe o valor).")
    if command and (ENV_READ.search(command) or KEY_ECHO.search(command)):
        block("comando exporia a NVIDIA_API_KEY. Use 'agrck doctor' para verificar a configuração.")
    if command and RM_STUDY.search(command):
        block("exclusão recursiva de estudos/resultados: peça confirmação explícita ao usuário e "
              "faça-a manualmente se ele aprovar.")


if __name__ == "__main__":
    main()
