# Instalação do ambiente científico (Linux x86_64, Python 3.12)

```bash
git clone git@github.com:fatioleg/AgRCK4MolDocking.git && cd AgRCK4MolDocking
python3 -m venv .venv
git clone https://github.com/Arcadia-Science/agentic-pymol tools/agentic-pymol   # MCP do PyMOL (opcional)
.venv/bin/pip install -r pipeline/requirements.txt
mkdir -p ~/.config/agrck && cp pipeline/.env.example ~/.config/agrck/.env && chmod 600 ~/.config/agrck/.env
#   edite ~/.config/agrck/.env no editor (NVIDIA_API_KEY de build.nvidia.com/mit/diffdock). Nunca cole no chat.
```

O `bin/agrck` usa `.venv/bin/python` automaticamente. Em outro local, use `export AGRCK_PYTHON=...`.

## GNINA 1.3.3 (CPU ou GPU)
```bash
mkdir -p ~/.local/opt/gnina && cd ~/.local/opt/gnina
curl -L -o gnina.1.3.3 https://github.com/gnina/gnina/releases/download/v1.3.3/gnina.cuda12.8.static
chmod +x gnina.1.3.3
python3 -m pip install --target cuda-libs "nvidia-cuda-runtime-cu12==12.8.*" "nvidia-cublas-cu12==12.8.*" \
  nvidia-cusparse-cu12 nvidia-cufft-cu12 nvidia-cusolver-cu12 "nvidia-nvjitlink-cu12==12.8.*" "nvidia-cudnn-cu12==9.*"
cat > gnina <<'EOF'
#!/bin/sh
D="$(dirname "$(readlink -f "$0")")"
LIBS=$(ls -d "$D"/cuda-libs/nvidia/*/lib | tr '\n' ':')
LD_LIBRARY_PATH="$LIBS${LD_LIBRARY_PATH}" exec "$D/gnina.1.3.3" "$@"
EOF
chmod +x gnina && ln -sf ~/.local/opt/gnina/gnina ~/.local/bin/gnina
```
GPUs Pascal (sm_61) não rodam o build CUDA 12.8. Nesse caso, mantenha `gnina.use_gpu: false`.

## PyMOL open-source para figuras
Uma das opções:
- `pip install pymol-open-source-whl` (já está no `requirements.txt`);
- `conda create -n pymol_os -c conda-forge pymol-open-source pyyaml pillow`, e depois
  `export AGRCK_PYMOL_PYTHON=$CONDA_PREFIX/bin/python`.

Não use builds que carimbam "evaluation" sem licença.

## Verificar
```bash
bin/agrck doctor
.venv/bin/python -m pytest -q tests
```
Versões fixadas: `numpy==1.26.4` (o wheel do PyMOL quebra com numpy 2) e `mcp==1.28.1` (o Agentic PyMOL usa a
API v1).

## Execução remota
Se o pipeline roda num servidor (ex.: `ssh myhome`), instale lá e use no `estudo.yaml`:
- `execucao.onde: ssh`;
- `host_ssh: myhome`;
- `dir_remoto: ~/AgRCK4MolDocking`.

O agente sincroniza `estudos/<ID>` nos dois sentidos, sem copiar o `.env`.
