"""Configuracoes do usuario, num arquivo simples ao lado do executavel.

O programa e distribuido como um arquivo unico (`.AppImage` no Linux,
`.exe` no Windows) e se comporta como programa portatil: as preferencias ficam
num `gc3d.ini` na MESMA PASTA do executavel, nao espalhadas pelo sistema. Quem
quiser levar o conversor num pendrive leva as configuracoes junto.

O formato e INI de proposito: da para abrir no bloco de notas e corrigir um
caminho a mao, o que um JSON de uma linha nao oferece. Nada aqui e critico, e um
arquivo corrompido ou editado errado nunca impede o programa de abrir.


Onde fica o arquivo
-------------------

Descobrir "a pasta do executavel" tem duas pegadinhas, e as duas ja morderam
este projeto:

* Empacotado em arquivo unico pelo PyInstaller, `__file__` aponta para a pasta
  temporaria onde o binario se descompactou (algo como `/tmp/_MEIxxxxxx`), que
  desaparece quando o programa fecha. O caminho do executavel de verdade e o
  `sys.executable`.

* Num AppImage, `sys.executable` aponta para dentro do sistema de arquivos
  montado em `/tmp/.mount_XXXXXX`, que e SOMENTE LEITURA. O caminho do arquivo
  `.AppImage` de verdade vem da variavel de ambiente `APPIMAGE`, exportada pelo
  AppRun.

Por isso a ordem e `APPIMAGE`, depois `sys.executable`, e so entao `__file__`
para quem roda pelo codigo-fonte.

Se essa pasta nao aceitar escrita — AppImage num CD ou pendrive travado, `.exe`
dentro de `Program Files`, que exige administrador — cai para a pasta de
configuracao do sistema (`~/.config/gc3d` ou `%APPDATA%\\gc3d`). A interface diz
no registro onde salvou, para o usuario nunca ficar procurando.
"""

from __future__ import annotations

import configparser
import os
import sys

__all__ = [
    "Settings",
    "config_path",
    "executable_dir",
    "fallback_dir",
    "CONFIG_NAME",
]

#: Nome do arquivo de configuracao. Fica ao lado do executavel.
CONFIG_NAME = "gc3d.ini"

#: Secao unica do INI. Uma secao so, porque nao ha o que agrupar.
SECTION = "gc3d"

#: O configparser so entende yes/no/true/false/on/off/1/0. Gravamos em portugues,
#: para o arquivo ficar legivel para quem vai edita-lo, e ensinamos sim/nao ao
#: leitor. As formas em ingles continuam valendo, porque alguem que edite a mao
#: pode escrever "true" por costume e nao ha razao para punir isso.
BOOLEAN_STATES = {
    "sim": True,
    "nao": False,
    "não": False,
    "s": True,
    "n": False,
    "yes": True,
    "no": False,
    "true": True,
    "false": False,
    "on": True,
    "off": False,
    "1": True,
    "0": False,
}


def _parser() -> configparser.RawConfigParser:
    """Leitor de INI configurado do jeito que este arquivo precisa.

    RawConfigParser, e nao ConfigParser: a interpolacao do ConfigParser trata
    '%' como escape e explode num caminho de Windows do tipo
    C:\\Users\\%USERNAME%\\saida, que e justamente o que guardamos aqui.
    """
    parser = configparser.RawConfigParser()
    parser.BOOLEAN_STATES = BOOLEAN_STATES
    return parser


def executable_dir() -> str:
    """Pasta onde o programa foi executado, do ponto de vista do usuario.

    Para um AppImage e a pasta que contem o arquivo `.AppImage`; para um `.exe`
    empacotado, a pasta que contem o `.exe`; rodando pelo codigo-fonte, a pasta
    do projeto.
    """
    # AppImage: o AppRun exporta APPIMAGE com o caminho do arquivo original.
    # Sem isso cairiamos no /tmp/.mount_XXXXXX somente leitura.
    appimage = os.environ.get("APPIMAGE")
    if appimage:
        directory = os.path.dirname(os.path.abspath(appimage))
        if directory:
            return directory

    # PyInstaller: sys.frozen marca o binario empacotado. sys.executable e o
    # caminho real do binario; __file__ seria a pasta temporaria de extracao.
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))

    # Rodando pelo codigo-fonte: a raiz do projeto (dois niveis acima daqui,
    # porque este arquivo esta em src/gc3d/).
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def fallback_dir() -> str:
    """Pasta de configuracao do sistema, usada quando a do executavel e travada."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Roaming"
        )
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            os.path.expanduser("~"), ".config"
        )
    return os.path.join(base, "gc3d")


def _writable(directory: str) -> bool:
    """A pasta aceita escrita?

    Testa criando e apagando um arquivo, em vez de usar `os.access`, que mente
    em vários casos: no Windows ele ignora as ACLs e diz que `Program Files` e
    gravavel, e em Linux ele responde sim para o root mesmo em montagem `ro`.
    """
    probe = os.path.join(directory, ".gc3d-teste-de-escrita")
    try:
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("")
    except OSError:
        return False
    else:
        try:
            os.remove(probe)
        except OSError:
            pass
        return True


def config_path() -> str:
    """Caminho do `gc3d.ini` que sera usado nesta execucao.

    Prefere a pasta do executavel. Se ela nao aceitar escrita, usa a pasta de
    configuracao do sistema. Um arquivo que ja exista ao lado do executavel
    ganha de tudo: se o usuario levou o programa e o INI juntos, e aquele INI
    que vale.
    """
    beside = os.path.join(executable_dir(), CONFIG_NAME)
    if os.path.isfile(beside):
        return beside
    if _writable(executable_dir()):
        return beside

    directory = fallback_dir()
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError:
        pass
    return os.path.join(directory, CONFIG_NAME)


class Settings:
    """Preferencias da interface, lidas e gravadas num INI.

    Nenhum metodo aqui levanta excecao por problema de arquivo. Preferencia
    perdida e um aborrecimento; programa que nao abre por causa de um INI
    ilegivel e um defeito.

    Uso:

        prefs = Settings.load()
        prefs.output_dir = "/tmp/saida"
        prefs.save()
    """

    #: Valores padrao. Tambem definem o tipo de cada chave na leitura.
    DEFAULTS: dict[str, object] = {
        "pasta_saida": "",
        "ultima_pasta_aberta": "",
        "incluir_textura": True,
        "juntar_tudo": True,
        "janela": "",
    }

    def __init__(self, path: str | None = None, **values: object) -> None:
        self.path = path or config_path()
        merged = dict(self.DEFAULTS)
        merged.update(values)
        self.pasta_saida: str = str(merged["pasta_saida"])
        self.ultima_pasta_aberta: str = str(merged["ultima_pasta_aberta"])
        self.incluir_textura: bool = bool(merged["incluir_textura"])
        self.juntar_tudo: bool = bool(merged["juntar_tudo"])
        self.janela: str = str(merged["janela"])

    # ------------------------------------------------------------------ leitura

    @classmethod
    def load(cls, path: str | None = None) -> Settings:
        """Le o INI. Arquivo ausente, ilegivel ou corrompido devolve os padroes."""
        target = path or config_path()
        parser = _parser()
        try:
            with open(target, encoding="utf-8") as handle:
                parser.read_file(handle)
        except (OSError, configparser.Error):
            return cls(path=target)

        if not parser.has_section(SECTION):
            return cls(path=target)

        values: dict[str, object] = {}
        for key, default in cls.DEFAULTS.items():
            if not parser.has_option(SECTION, key):
                continue
            if isinstance(default, bool):
                try:
                    values[key] = parser.getboolean(SECTION, key)
                except ValueError:
                    # Chave editada a mao com algo que nao e sim/nao: ignora e
                    # fica com o padrao.
                    continue
            else:
                values[key] = parser.get(SECTION, key)
        return cls(path=target, **values)

    # ------------------------------------------------------------------ escrita

    def save(self) -> bool:
        """Grava o INI. Devolve se conseguiu, sem levantar excecao."""
        parser = _parser()
        parser.add_section(SECTION)
        parser.set(SECTION, "pasta_saida", self.pasta_saida)
        parser.set(SECTION, "ultima_pasta_aberta", self.ultima_pasta_aberta)
        parser.set(SECTION, "incluir_textura", "sim" if self.incluir_textura else "nao")
        parser.set(SECTION, "juntar_tudo", "sim" if self.juntar_tudo else "nao")
        parser.set(SECTION, "janela", self.janela)

        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as handle:
                handle.write(_HEADER)
                parser.write(handle)
        except OSError:
            return False
        return True


#: Cabecalho explicativo, para quem abrir o arquivo no bloco de notas.
_HEADER = """\
# Configuracoes do Grand Chase 3D Importer.
#
# Gravado automaticamente quando o programa fecha. Pode editar a mao: use
# sim/nao nas opcoes de ligar e desligar, e caminhos completos nas pastas.
# Apagar este arquivo devolve tudo ao padrao.

"""
