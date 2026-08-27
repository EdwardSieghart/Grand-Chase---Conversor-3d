#!/usr/bin/env bash
# Publica este projeto no GitHub: envia o codigo e, opcionalmente, anexa os
# pacotes prontos como uma Release.
#
# ---------------------------------------------------------------------------
# O QUE VOCE PRECISA
# ---------------------------------------------------------------------------
# O e-mail da conta NAO e suficiente. O GitHub desativou autenticacao por senha
# em 2021; o e-mail so serve para assinar os commits. Para enviar codigo, escolha
# uma das duas formas:
#
# OPCAO A — token pessoal (mais rapido; cria o repositorio automaticamente)
#   1. Va em https://github.com/settings/tokens
#      "Generate new token (classic)", marque APENAS o escopo  repo
#   2. Rode:
#        read -rs GITHUB_TOKEN && export GITHUB_TOKEN     # cole o token, Enter
#        ./tools/publicar_github.sh SEU_USUARIO grand-chase-3d-importer
#
#      Lendo com 'read -rs' o token nao fica no historico do shell.
#
# OPCAO B — chave SSH (melhor para uso continuado)
#   1. ssh-keygen -t ed25519 -C "seu-email@exemplo.com"
#   2. cat ~/.ssh/id_ed25519.pub        e cole em https://github.com/settings/keys
#   3. Crie o repositorio VAZIO em https://github.com/new
#      (sem README, sem .gitignore, sem licenca)
#   4. ./tools/publicar_github.sh SEU_USUARIO grand-chase-3d-importer --ssh
#
# ---------------------------------------------------------------------------
# ANEXAR OS PACOTES PRONTOS (precisa de token)
# ---------------------------------------------------------------------------
#   python3 build/empacotar.py --zip
#   ./tools/publicar_github.sh SEU_USUARIO REPO --release
#
# Os .zip vao como arquivos de uma Release, nao como commits. Isso e de proposito:
# um binario de 26 MB commitado fica no historico do git para sempre, e cada
# recompilacao somaria outros 26 MB. Numa Release o arquivo pode ser substituido
# e nao pesa no clone.
#
# ---------------------------------------------------------------------------
# DEPOIS DA PRIMEIRA VEZ
# ---------------------------------------------------------------------------
#   git add -A && git commit -m "descricao" && git push
#   git tag -a v1.5.0 -m "descricao" && git push --tags

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

show_help() {
    sed -n '2,45p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

if [ $# -lt 2 ]; then
    show_help
    exit 2
fi

USUARIO="$1"
REPO="$2"
shift 2

USE_SSH=0
DO_RELEASE=0
for arg in "$@"; do
    case "$arg" in
        --ssh) USE_SSH=1 ;;
        --release) DO_RELEASE=1 ;;
        -h|--help) show_help; exit 0 ;;
        *) echo "opcao desconhecida: $arg" >&2; exit 2 ;;
    esac
done

api() {
    # api <metodo> <caminho> [dados]
    local metodo="$1" caminho="$2" dados="${3:-}"
    if [ -n "$dados" ]; then
        curl -sS -X "$metodo" \
            -H "Authorization: Bearer $GITHUB_TOKEN" \
            -H "Accept: application/vnd.github+json" \
            -d "$dados" \
            "https://api.github.com$caminho"
    else
        curl -sS -X "$metodo" \
            -H "Authorization: Bearer $GITHUB_TOKEN" \
            -H "Accept: application/vnd.github+json" \
            "https://api.github.com$caminho"
    fi
}

# ---------------------------------------------------------------- verificacoes

if [ ! -d .git ]; then
    echo "ERRO: nao ha repositorio git em $PROJECT_ROOT." >&2
    exit 1
fi

if ! git rev-parse HEAD >/dev/null 2>&1; then
    echo "ERRO: nenhum commit ainda. Rode antes:" >&2
    echo "  git add -A && git commit -m 'commit inicial'" >&2
    exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
    echo "AVISO: ha alteracoes nao commitadas. Elas NAO serao enviadas."
    git status --short
    echo
    read -rp "Continuar mesmo assim? [s/N] " resposta
    case "$resposta" in
        s|S|y|Y) ;;
        *) echo "cancelado."; exit 1 ;;
    esac
fi

# A identidade fica gravada em cada commit; vale corrigir antes de publicar.
EMAIL_ATUAL="$(git config user.email || echo '')"
if [ "$EMAIL_ATUAL" = "eduardo@localhost" ]; then
    NOME_ATUAL="$(git config user.name || echo '')"
    echo "AVISO: os commits estao assinados como '$NOME_ATUAL <$EMAIL_ATUAL>'."
    echo "       Para o GitHub associa-los a sua conta, use o e-mail da conta:"
    echo "         git config user.name  \"Seu Nome\""
    echo "         git config user.email \"seu-email-do-github@exemplo.com\""
    echo "       Para reassinar o ultimo commit:"
    echo "         git commit --amend --reset-author --no-edit"
    echo
fi

if [ "$DO_RELEASE" -eq 1 ] && [ "$USE_SSH" -eq 1 ]; then
    echo "ERRO: --release precisa de token (a API do GitHub nao usa SSH)." >&2
    exit 1
fi

# ------------------------------------------------------------------ publicacao

if [ "$USE_SSH" -eq 1 ]; then
    REMOTE_URL="git@github.com:$USUARIO/$REPO.git"
    echo "==> Usando SSH: $REMOTE_URL"
    echo "    (o repositorio precisa ja existir e estar vazio no GitHub)"
else
    if [ -z "${GITHUB_TOKEN:-}" ]; then
        echo "ERRO: variavel GITHUB_TOKEN nao definida." >&2
        echo "      Defina com:  read -rs GITHUB_TOKEN && export GITHUB_TOKEN" >&2
        echo "      Ou use SSH:  $0 $USUARIO $REPO --ssh" >&2
        exit 1
    fi

    echo "==> Verificando se o repositorio $USUARIO/$REPO existe"
    STATUS=$(curl -sS -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer $GITHUB_TOKEN" \
        -H "Accept: application/vnd.github+json" \
        "https://api.github.com/repos/$USUARIO/$REPO")

    case "$STATUS" in
        404)
            echo "==> Criando o repositorio $USUARIO/$REPO"
            RESPOSTA=$(api POST /user/repos "$(cat <<JSON
{"name":"$REPO",
 "description":"Conversor bidirecional de modelos e animacoes do Grand Chase (P3M/FRM) para glTF, para Linux e Windows",
 "private":false}
JSON
)")
            if ! echo "$RESPOSTA" | grep -q '"full_name"'; then
                echo "ERRO ao criar o repositorio:" >&2
                echo "$RESPOSTA" | head -20 >&2
                exit 1
            fi
            echo "    criado."
            ;;
        200) echo "    ja existe, sera reutilizado." ;;
        401)
            echo "ERRO: token invalido ou expirado (HTTP 401)." >&2
            exit 1
            ;;
        *)
            echo "ERRO: resposta inesperada da API do GitHub (HTTP $STATUS)." >&2
            exit 1
            ;;
    esac

    REMOTE_URL="https://github.com/$USUARIO/$REPO.git"
fi

if git remote get-url origin >/dev/null 2>&1; then
    git remote set-url origin "$REMOTE_URL"
else
    git remote add origin "$REMOTE_URL"
fi
echo "==> remote origin: $REMOTE_URL"

RAMO="$(git rev-parse --abbrev-ref HEAD)"
echo "==> Enviando o ramo '$RAMO' e as tags"

if [ "$USE_SSH" -eq 1 ]; then
    git push -u origin "$RAMO"
    git push origin --tags
else
    # O token vai apenas na URL desta invocacao, nunca gravado como remote, para
    # nao ficar em .git/config em texto claro.
    git -c credential.helper= \
        push "https://$USUARIO:$GITHUB_TOKEN@github.com/$USUARIO/$REPO.git" \
        "$RAMO" --tags
    git branch --set-upstream-to="origin/$RAMO" "$RAMO" 2>/dev/null || true
fi

echo
echo "==> Codigo publicado: https://github.com/$USUARIO/$REPO"

# --------------------------------------------------------------------- Release

if [ "$DO_RELEASE" -eq 0 ]; then
    echo
    echo "Para anexar os pacotes prontos (executaveis) como Release:"
    echo "    python3 build/empacotar.py --zip"
    echo "    $0 $USUARIO $REPO --release"
    exit 0
fi

VERSAO="$(python3 - <<'PY'
import re, pathlib
texto = pathlib.Path("src/gc3d/__init__.py").read_text(encoding="utf-8")
print(re.search(r'__version__\s*=\s*"([^"]+)"', texto).group(1))
PY
)"
TAG="v$VERSAO"

mapfile -t PACOTES < <(find release -maxdepth 1 -name "*.zip" -type f | sort)
if [ "${#PACOTES[@]}" -eq 0 ]; then
    echo "ERRO: nenhum .zip em release/. Gere com:" >&2
    echo "    python3 build/empacotar.py --zip" >&2
    exit 1
fi

echo
echo "==> Preparando a Release $TAG com ${#PACOTES[@]} pacote(s)"
for pacote in "${PACOTES[@]}"; do
    echo "    $(basename "$pacote")  ($(du -h "$pacote" | cut -f1))"
done

EXISTENTE=$(api GET "/repos/$USUARIO/$REPO/releases/tags/$TAG")
RELEASE_ID=$(echo "$EXISTENTE" | sed -n 's/.*"id": *\([0-9]\+\).*/\1/p' | head -1)

if [ -z "$RELEASE_ID" ]; then
    echo "==> Criando a Release $TAG"
    CORPO=$(cat <<JSON
{"tag_name":"$TAG",
 "name":"Grand Chase 3D Importer $VERSAO",
 "body":"Pacotes prontos para usar.\\n\\n- **GrandChase3D-Windows** — descompacte e execute *Converter.bat*\\n- **GrandChase3D-Linux** — descompacte e execute *Converter.sh*\\n\\nCada pasta traz o LEIA-ME, exemplos para testar e funciona com ou sem Python instalado.",
 "draft":false,
 "prerelease":false}
JSON
)
    RESPOSTA=$(api POST "/repos/$USUARIO/$REPO/releases" "$CORPO")
    RELEASE_ID=$(echo "$RESPOSTA" | sed -n 's/.*"id": *\([0-9]\+\).*/\1/p' | head -1)
    if [ -z "$RELEASE_ID" ]; then
        echo "ERRO ao criar a Release:" >&2
        echo "$RESPOSTA" | head -20 >&2
        exit 1
    fi
else
    echo "==> Release $TAG ja existe (id $RELEASE_ID), atualizando os anexos"
fi

for pacote in "${PACOTES[@]}"; do
    nome="$(basename "$pacote")"
    # Remove um anexo com o mesmo nome, se houver: a API recusa duplicatas.
    ANEXOS=$(api GET "/repos/$USUARIO/$REPO/releases/$RELEASE_ID/assets")
    ANTIGO=$(echo "$ANEXOS" | python3 -c "
import json,sys
try: dados=json.load(sys.stdin)
except Exception: sys.exit()
for item in dados if isinstance(dados,list) else []:
    if item.get('name')=='$nome': print(item['id'])
" | head -1)
    if [ -n "$ANTIGO" ]; then
        echo "    substituindo $nome"
        api DELETE "/repos/$USUARIO/$REPO/releases/assets/$ANTIGO" >/dev/null
    fi

    echo "    enviando $nome"
    curl -sS -X POST \
        -H "Authorization: Bearer $GITHUB_TOKEN" \
        -H "Content-Type: application/zip" \
        --data-binary "@$pacote" \
        "https://uploads.github.com/repos/$USUARIO/$REPO/releases/$RELEASE_ID/assets?name=$nome" \
        | grep -q '"state"' || {
            echo "ERRO ao enviar $nome" >&2
            exit 1
        }
done

echo
echo "==> Release publicada:"
echo "    https://github.com/$USUARIO/$REPO/releases/tag/$TAG"
