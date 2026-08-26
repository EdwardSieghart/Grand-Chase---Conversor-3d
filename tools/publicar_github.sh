#!/usr/bin/env bash
# Publica este repositorio no GitHub.
#
# O repositorio local ja esta pronto e commitado; falta apenas enviar. Este
# script cuida das duas formas de autenticacao.
#
# ---------------------------------------------------------------------------
# OPCAO A — token pessoal (mais rapido; cria o repositorio automaticamente)
# ---------------------------------------------------------------------------
# 1. Gere um token em: https://github.com/settings/tokens
#    - "Generate new token (classic)"
#    - marque apenas o escopo  repo
# 2. Rode:
#      export GITHUB_TOKEN=ghp_seutoken
#      ./tools/publicar_github.sh SEU_USUARIO grand-chase-3d-importer
#
#    O token e lido da variavel de ambiente, nunca fica gravado em arquivo nem
#    aparece na saida. Para nao deixa-lo no historico do shell, prefira:
#      read -rs GITHUB_TOKEN && export GITHUB_TOKEN
#
# ---------------------------------------------------------------------------
# OPCAO B — chave SSH (melhor para uso continuado)
# ---------------------------------------------------------------------------
# 1. Gere a chave:
#      ssh-keygen -t ed25519 -C "seu-email@exemplo.com"
# 2. Copie a chave publica:
#      cat ~/.ssh/id_ed25519.pub
# 3. Cole em: https://github.com/settings/keys
# 4. Crie o repositorio VAZIO em https://github.com/new
#    (sem README, sem .gitignore, sem licenca)
# 5. Rode:
#      ./tools/publicar_github.sh SEU_USUARIO grand-chase-3d-importer --ssh
#
# ---------------------------------------------------------------------------
# Depois da primeira publicacao, para salvar novas versoes:
#      git add -A
#      git commit -m "descricao da mudanca"
#      git push
#      # e, ao marcar uma versao:
#      git tag -a v1.1.0 -m "descricao"
#      git push --tags

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [ $# -lt 2 ]; then
    sed -n '2,45p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 2
fi

USUARIO="$1"
REPO="$2"
USE_SSH=0
if [ "${3:-}" = "--ssh" ]; then
    USE_SSH=1
fi

# ---------------------------------------------------------------- verificacoes

if [ ! -d .git ]; then
    echo "ERRO: nao ha repositorio git aqui ($PROJECT_ROOT)." >&2
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

# A identidade esta configurada apenas neste repositorio, com um valor
# provisorio. Vale a pena corrigir antes de publicar, porque o nome e o e-mail
# ficam gravados em cada commit.
NOME_ATUAL="$(git config user.name || echo '')"
EMAIL_ATUAL="$(git config user.email || echo '')"
if [ "$EMAIL_ATUAL" = "eduardo@localhost" ]; then
    echo "AVISO: os commits estao assinados como '$NOME_ATUAL <$EMAIL_ATUAL>'."
    echo "       Para o GitHub associar os commits a sua conta, configure:"
    echo "         git config user.name  \"Seu Nome\""
    echo "         git config user.email \"seu-email-do-github@exemplo.com\""
    echo "       (e, para reassinar o commit existente:"
    echo "         git commit --amend --reset-author --no-edit )"
    echo
fi

# ---------------------------------------------------------------- publicacao

if [ "$USE_SSH" -eq 1 ]; then
    REMOTE_URL="git@github.com:$USUARIO/$REPO.git"
    echo "==> Usando SSH: $REMOTE_URL"
    echo "    (o repositorio precisa ja existir e estar vazio no GitHub)"
else
    if [ -z "${GITHUB_TOKEN:-}" ]; then
        echo "ERRO: variavel GITHUB_TOKEN nao definida." >&2
        echo "      Defina com:  read -rs GITHUB_TOKEN && export GITHUB_TOKEN" >&2
        echo "      Ou use a opcao SSH:  $0 $USUARIO $REPO --ssh" >&2
        exit 1
    fi

    echo "==> Verificando se o repositorio $USUARIO/$REPO existe"
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer $GITHUB_TOKEN" \
        -H "Accept: application/vnd.github+json" \
        "https://api.github.com/repos/$USUARIO/$REPO")

    if [ "$STATUS" = "404" ]; then
        echo "==> Criando o repositorio $USUARIO/$REPO"
        RESPOSTA=$(curl -s -X POST \
            -H "Authorization: Bearer $GITHUB_TOKEN" \
            -H "Accept: application/vnd.github+json" \
            -d "{\"name\":\"$REPO\",\"description\":\"Conversor de modelos e animacoes do Grand Chase (P3M/FRM) para glTF, para Linux e Windows\",\"private\":false}" \
            "https://api.github.com/user/repos")
        if ! echo "$RESPOSTA" | grep -q '"full_name"'; then
            echo "ERRO ao criar o repositorio:" >&2
            echo "$RESPOSTA" | head -20 >&2
            exit 1
        fi
        echo "    criado."
    elif [ "$STATUS" = "200" ]; then
        echo "    ja existe, sera reutilizado."
    elif [ "$STATUS" = "401" ]; then
        echo "ERRO: token invalido ou expirado (HTTP 401)." >&2
        exit 1
    else
        echo "ERRO: resposta inesperada da API do GitHub (HTTP $STATUS)." >&2
        exit 1
    fi

    # O token vai apenas na URL usada nesta invocacao do push, nunca gravado
    # como remote, para nao ficar em .git/config em texto claro.
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
    git -c credential.helper= \
        push "https://$USUARIO:$GITHUB_TOKEN@github.com/$USUARIO/$REPO.git" \
        "$RAMO" --tags
    git branch --set-upstream-to="origin/$RAMO" "$RAMO" 2>/dev/null || true
fi

echo
echo "==> Publicado: https://github.com/$USUARIO/$REPO"
echo
echo "Para salvar as proximas versoes:"
echo "  git add -A && git commit -m \"descricao\" && git push"
