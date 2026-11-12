"""
Decides whether a goal needs an agent harness (to read or change the user's files, or run commands on their
machine) or can be answered directly by a model. Rules, not a model call: instant, offline and deterministic,
which matters most for local use. English and Spanish.

A goal needs the workspace when it:
  A. names a file or project path:                      "Update the version in package.json", "Look at src/"
  B. points at the user's own work:                     "this code", "my changes", "este proyecto"
  C. gives a command about a specific workspace thing:  "Install the dependencies", "Ejecuta los tests"
     (a determiner such as the/my/los marks it as theirs: "Write a function" is a request for a snippet)
  D. asks why something of theirs is broken:            "Why is the build failing?"
  E. matches a known workspace phrase:                  "git status", "will this compile?", "run tests"
  F. asks to find out how to run something:             "Can u help me find how to run the HUD?"
     (only the user's own files can say how their thing starts)
How-to and explanation questions ("How do I write a test in pytest?") stay direct unless A, B or D applies.

Measured with `emiliano eval routing`, which keeps a held-out set the rules were not written against.
"""

from __future__ import annotations

import re

_EXTENSIONS = (
    "py|pyi|ipynb|js|jsx|mjs|cjs|ts|tsx|vue|svelte|json|jsonc|ya?ml|toml|ini|cfg|conf|env|lock|md|mdx|rst|txt|csv|"
    "html?|css|scss|sass|less|xml|svg|rs|go|java|kts?|scala|cs|fs|cpp|cc|cxx|c|h|hpp|m|mm|swift|rb|php|pl|lua|r|"
    "dart|ex|exs|erl|hs|clj|sh|bash|zsh|ps1|psm1|bat|cmd|sql|graphql|proto|tf|gradle|dockerfile|makefile"
)
# file.ext or dir/file.ext; the name must start with a letter, digit or underscore (".gitignore" is a concept)
_FILE = re.compile(rf"(?<![\w./-])(?:[\w.-]+/)*\w[\w.-]*\.(?:{_EXTENSIONS})\b", re.IGNORECASE)
# Library names that look like files: "Node.js", "Vue.js"
_NOT_FILES = re.compile(r"\b(?:node|vue|next|nuxt|three|express|react|angular|d3|chart|socket|ember|backbone)\.js\b",
                        re.IGNORECASE)
_FOLDERS = "src|lib|app|apps|tests?|spec|docs|scripts|packages|config|public|components|pages|utils|bin|build|dist"
_PATH = re.compile(rf"(?:^|[\s`'\"(])(?:\.{{1,2}}/|~/|(?:{_FOLDERS})/)", re.IGNORECASE)

# Things in a workspace (English, Spanish)
_NOUNS = (
    r"files?|folders?|director(?:y|ies)|code|codebase|repo|repository|project|tests?|test suite|specs?|"
    r"functions?|methods?|class(?:es)?|modules?|imports?|dependencies|deps|packages?|server|build|branch|"
    r"changes|commits?|app|application|config(?:uration)?|readme|docs|scripts?|components?|endpoints?|routes?|"
    r"migrations?|bugs?|errors?|failures?|logs?|todos?|variables?|workspace|"
    r"archivos?|ficheros?|carpetas?|directorios?|c[oó]digo|repositorio|proyecto|pruebas|funci[oó]n|funciones|"
    r"m[eé]todos?|clases?|m[oó]dulos?|importaciones|dependencias|paquetes|servidor|compilaci[oó]n|rama|cambios|"
    r"aplicaci[oó]n|configuraci[oó]n|documentaci[oó]n|componentes?|errores|error|fallos?|variables?"
)
_DEICTIC = r"this|these|my|our|este|esta|estos|estas|mi|mis|nuestro|nuestra|nuestros|nuestras"
_DETERMINERS = rf"the|those|all(?: the)?|every|its|{_DEICTIC}|el|la|los|las|tu|tus|su|sus|todos los|todas las"
# Up to two words between the determiner and the noun: "the parser module", "the unused imports"
_OWN_WORK = re.compile(rf"\b(?:{_DEICTIC})\s+(?:[\w-]+\s+)?(?:{_NOUNS})\b", re.IGNORECASE)
_SPECIFIC_THING = re.compile(rf"\b(?:{_DETERMINERS})\s+(?:[\w-]+\s+){{0,2}}(?:{_NOUNS})\b", re.IGNORECASE)
_BARE_THING = re.compile(r"\b(?:files|tests|dependencies|imports|migrations|archivos|pruebas|dependencias)\b",
                         re.IGNORECASE)

_VERBS = (
    r"fix|update|add|remove|delete|rename|refactor|run|execute|install|uninstall|commit|push|pull|merge|"
    r"create|implement|debug|build|compile|start|stop|restart|deploy|review|inspect|check|scan|audit|look|find|"
    r"search|grep|list|move|format|lint|migrate|upgrade|bump|clean|open|edit|change|modify|replace|write|"
    r"generate|test|document|split|extract|optimi[sz]e|"
    r"arregla|corrige|actualiza|añade|agrega|elimina|borra|quita|renombra|refactoriza|ejecuta|corre|lanza|"
    r"instala|crea|implementa|depura|compila|inicia|arranca|despliega|revisa|inspecciona|busca|lista|mueve|"
    r"cambia|modifica|reemplaza|escribe|genera|prueba|documenta|"
    r"arreglar|corregir|actualizar|añadir|agregar|eliminar|borrar|renombrar|ejecutar|instalar|crear|revisar|"
    r"buscar|cambiar|modificar|escribir|encontrar|averiguar"
)
_POLITE = (r"(?:please\s+|pls\s+|(?:can|could|would) (?:you|u)\s+(?:please\s+)?(?:help me\s+(?:to\s+)?)?|"
           r"help me\s+(?:to\s+)?|por favor\s+|puedes\s+|podr[ií]as\s+|ay[uú]dame a\s+)?")
_COMMAND = re.compile(rf"^\W*{_POLITE}(?:{_VERBS})\b", re.IGNORECASE)

_BROKEN = re.compile(
    r"\b(?:fail(?:s|ing|ed)?|broken|break(?:s|ing)?|crash(?:es|ing)?|not working|doesn'?t work|won'?t (?:build|run|start)|"
    r"falla[n]?|fallando|roto|rota|no funciona|no compila|no arranca)\b", re.IGNORECASE)
_QUESTION = re.compile(
    r"^\W*(?:how|what|what's|whats|why|when|which|who|where|explain|describe|tell me|is there|are there|"
    r"c[oó]mo|qu[eé]|por qu[eé]|cu[aá]ndo|cu[aá]l|qui[eé]n|d[oó]nde|explica|describe|dime)\b", re.IGNORECASE)

# Phrases that always mean the workspace (kept from the original keyword router)
_PHRASES = (
    "in the current folder", "in current directory", "the files in", "files in this", "local files",
    "does it compile", "can it compile", "will it compile", "will compile", "build the project", "build the code",
    "git status", "git diff", "git commit", "git push", "git log", "git add",
)


# "Find how to run the HUD", "busca cómo arrancar el dock": how something of theirs starts is in their files
_FIND_HOW_TO_RUN = re.compile(
    r"\b(?:find|locate|search|figure out|look up|busca|encuentra|averigua|buscar|encontrar|averiguar)\b.{0,30}?"
    r"\b(?:how\s+(?:to|can i|do i|could i|i can|should i)|c[oó]mo(?:\s+puedo)?)\s+"
    r"(?:run|start|launch|open|execute|ejecutar|correr|arrancar|iniciar|abrir|lanzar)\b",
    re.IGNORECASE)

# "Will this compile?", "does it run?": "this"/"it" without a noun is the user's own code
_DOES_IT_RUN = re.compile(
    r"\b(?:will|does|did|can|would|could|is)\s+(?:this|it)\s+(?:still\s+)?(?:compile|build|run|work|pass)|"
    r"\b(?:esto|eso)?\s*(?:compila|funciona|arranca)\s*\?", re.IGNORECASE)


def mentions_file(goal: str) -> bool:
    text = _NOT_FILES.sub(" ", goal)
    return bool(_FILE.search(text) or _PATH.search(text))


def needs_workspace(goal: str) -> bool:
    """True when answering the goal needs the user's files or machine, so an agent harness should run it."""
    g = " ".join(goal.split())
    low = g.lower()
    if mentions_file(g) or _OWN_WORK.search(g):                          # A, B
        return True
    specific = _SPECIFIC_THING.search(g)
    if specific and _BROKEN.search(g):                                   # D
        return True
    if any(phrase in low for phrase in _PHRASES) or _DOES_IT_RUN.search(g):  # E
        return True
    if _QUESTION.search(g):
        return False
    if _COMMAND.search(g) and _FIND_HOW_TO_RUN.search(g):               # F
        return True
    if _COMMAND.search(g) and (specific or _BARE_THING.search(g)):       # C
        return True
    # "run tests", "npm test" as a command, even without a determiner
    return bool(re.search(r"\b(?:run|ejecuta|corre)\s+(?:the\s+|los\s+)?(?:tests?|pruebas)\b|"
                          r"\b(?:pytest|npm test|cargo test|go test|yarn test)\b", low))
