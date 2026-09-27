"""What a roadblock is about: the error's type and core message, the packages and the stack it names.

A learner pastes a traceback or says "my Svelte app gets a CORS error from FastAPI". The public sources are
searched with a compact signature — never with their file paths, ports, hostnames or long numbers, which are
theirs alone and only make a search worse (and would leave the computer for nothing).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------- the stack: words → tags
# (Stack Overflow tag, package ecosystem or "", the project's GitHub repository for issue searches or "")
STACK: dict[str, tuple[str, str, str]] = {
    "python": ("python", "pypi", ""), "pip": ("python", "pypi", ""), "venv": ("python", "pypi", ""),
    "conda": ("python", "pypi", ""), "traceback": ("python", "pypi", ""), "pytest": ("pytest", "pypi", "pytest-dev/pytest"),
    "fastapi": ("fastapi", "pypi", "fastapi/fastapi"), "uvicorn": ("uvicorn", "pypi", "encode/uvicorn"),
    "starlette": ("starlette", "pypi", "encode/starlette"), "pydantic": ("pydantic", "pypi", "pydantic/pydantic"),
    "flask": ("flask", "pypi", "pallets/flask"), "django": ("django", "pypi", ""),
    "sqlalchemy": ("sqlalchemy", "pypi", "sqlalchemy/sqlalchemy"), "numpy": ("numpy", "pypi", "numpy/numpy"),
    "pandas": ("pandas", "pypi", "pandas-dev/pandas"), "matplotlib": ("matplotlib", "pypi", "matplotlib/matplotlib"),
    "sklearn": ("scikit-learn", "pypi", "scikit-learn/scikit-learn"),
    "scikit-learn": ("scikit-learn", "pypi", "scikit-learn/scikit-learn"),
    "pytorch": ("pytorch", "pypi", "pytorch/pytorch"), "torch": ("pytorch", "pypi", "pytorch/pytorch"),
    "tensorflow": ("tensorflow", "pypi", "tensorflow/tensorflow"), "keras": ("keras", "pypi", "keras-team/keras"),
    "opencv": ("opencv", "pypi", "opencv/opencv-python"), "cv2": ("opencv", "pypi", "opencv/opencv-python"),
    "mediapipe": ("mediapipe", "pypi", "google-ai-edge/mediapipe"), "langchain": ("langchain", "pypi", "langchain-ai/langchain"),
    "openai": ("openai-api", "pypi", "openai/openai-python"), "streamlit": ("streamlit", "pypi", "streamlit/streamlit"),
    "jupyter": ("jupyter-notebook", "pypi", ""), "selenium": ("selenium", "pypi", "SeleniumHQ/selenium"),
    "node": ("node.js", "npm", ""), "nodejs": ("node.js", "npm", ""), "node.js": ("node.js", "npm", ""),
    "npm": ("npm", "npm", ""), "yarn": ("yarn", "npm", ""), "pnpm": ("pnpm", "npm", "pnpm/pnpm"),
    "javascript": ("javascript", "npm", ""), "js": ("javascript", "npm", ""),
    "typescript": ("typescript", "npm", "microsoft/TypeScript"), "ts": ("typescript", "npm", ""),
    "react": ("reactjs", "npm", "facebook/react"), "reactjs": ("reactjs", "npm", "facebook/react"),
    "jsx": ("reactjs", "npm", ""), "next": ("next.js", "npm", "vercel/next.js"), "nextjs": ("next.js", "npm", "vercel/next.js"),
    "next.js": ("next.js", "npm", "vercel/next.js"), "svelte": ("svelte", "npm", "sveltejs/svelte"),
    "sveltekit": ("sveltekit", "npm", "sveltejs/kit"), "vue": ("vue.js", "npm", "vuejs/core"),
    "nuxt": ("nuxt.js", "npm", "nuxt/nuxt"), "angular": ("angular", "npm", "angular/angular"),
    "vite": ("vite", "npm", "vitejs/vite"), "webpack": ("webpack", "npm", "webpack/webpack"),
    "tailwind": ("tailwind-css", "npm", "tailwindlabs/tailwindcss"),
    "tailwindcss": ("tailwind-css", "npm", "tailwindlabs/tailwindcss"), "express": ("express", "npm", "expressjs/express"),
    "prisma": ("prisma", "npm", "prisma/prisma"), "mongoose": ("mongoose", "npm", "Automattic/mongoose"),
    "electron": ("electron", "npm", "electron/electron"), "expo": ("expo", "npm", "expo/expo"),
    "react-native": ("react-native", "npm", "facebook/react-native"), "three.js": ("three.js", "npm", "mrdoob/three.js"),
    "socket.io": ("socket.io", "npm", "socketio/socket.io"), "leaflet": ("leaflet", "npm", "Leaflet/Leaflet"),
    "docker": ("docker", "", ""), "dockerfile": ("docker", "", ""), "compose": ("docker-compose", "", ""),
    "git": ("git", "", ""), "github": ("github", "", ""), "cors": ("cors", "", ""),
    "websocket": ("websocket", "", ""), "websockets": ("websocket", "", ""),
    "postgres": ("postgresql", "", ""), "postgresql": ("postgresql", "", ""), "mysql": ("mysql", "", ""),
    "sqlite": ("sqlite", "", ""), "mongodb": ("mongodb", "", ""), "mongo": ("mongodb", "", ""),
    "redis": ("redis", "", ""), "firebase": ("firebase", "", ""), "supabase": ("supabase", "", "supabase/supabase"),
    "vercel": ("vercel", "", "vercel/vercel"), "netlify": ("netlify", "", ""), "heroku": ("heroku", "", ""),
    "aws": ("amazon-web-services", "", ""), "lambda": ("aws-lambda", "", ""), "gcp": ("google-cloud-platform", "", ""),
    "azure": ("azure", "", ""), "jwt": ("jwt", "", ""), "oauth": ("oauth-2.0", "", ""), "stripe": ("stripe-payments", "", ""),
    "twilio": ("twilio", "", ""), "flutter": ("flutter", "", "flutter/flutter"), "dart": ("dart", "", ""),
    "android": ("android", "", ""), "kotlin": ("kotlin", "", ""), "swift": ("swift", "", ""), "ios": ("ios", "", ""),
    "xcode": ("xcode", "", ""), "java": ("java", "", ""), "spring": ("spring-boot", "", ""), "golang": ("go", "", ""),
    "rust": ("rust", "", ""), "cargo": ("rust-cargo", "", ""), "c++": ("c++", "", ""), "cmake": ("cmake", "", ""),
    "arduino": ("arduino", "", ""), "esp32": ("esp32", "", ""), "raspberry": ("raspberry-pi", "", ""),
    "unity": ("unity-game-engine", "", ""), "godot": ("godot", "", "godotengine/godot"),
    "bluetooth": ("bluetooth", "", ""), "graphql": ("graphql", "", ""), "nginx": ("nginx", "", ""),
    "cloudflare": ("cloudflare", "", ""), "ngrok": ("ngrok", "", ""),
}
# how specific a tag is (a search is scoped by the most specific one)
_GENERIC_TAGS = {"python", "javascript", "node.js", "npm", "typescript", "java", "git", "github", "docker", "cors",
                 "c++", "go", "rust", "android", "ios", "swift", "kotlin", "dart"}

# Python import names that are not the package's name on PyPI (checked against PyPI before she says so)
IMPORT_TO_PYPI = {
    "cv2": "opencv-python", "PIL": "Pillow", "sklearn": "scikit-learn", "yaml": "PyYAML", "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv", "jwt": "PyJWT", "Crypto": "pycryptodome", "dateutil": "python-dateutil",
    "serial": "pyserial", "usb": "pyusb", "OpenSSL": "pyOpenSSL", "magic": "python-magic", "docx": "python-docx",
    "pptx": "python-pptx", "fitz": "PyMuPDF", "skimage": "scikit-image", "telegram": "python-telegram-bot",
    "attr": "attrs", "google.protobuf": "protobuf", "win32api": "pywin32", "win32com": "pywin32",
    "MySQLdb": "mysqlclient", "psycopg2": "psycopg2-binary", "speech_recognition": "SpeechRecognition",
    "Levenshtein": "python-Levenshtein", "discord": "discord.py", "socketio": "python-socketio",
}
NODE_BUILTINS = {"fs", "path", "os", "crypto", "http", "https", "child_process", "stream", "util", "events", "buffer",
                 "url", "net", "tls", "zlib", "worker_threads", "readline", "dns", "querystring", "assert"}

# ---------------------------------------------------------------------- error shapes
_PY_EXC = re.compile(r"^\s*(?:([\w.]+)\.)?([A-Z]\w*(?:Error|Exception|Warning|Exit|Interrupt))(?::\s*(.*))?\s*$", re.M)
_JS_EXC = re.compile(r"(?:Uncaught\s+)?(?:\(in promise\)\s+)?\b([A-Z]\w*(?:Error|Exception))\b(?::|\s+-)\s*([^\n]{3,})")
_CODE = re.compile(r"\b(E[A-Z]{3,}|ERR_[A-Z0-9_]{3,})\b")
_HTTP = re.compile(r"\b([45]\d\d)\b[\s:(\-]*(Not Found|Unauthorized|Forbidden|Bad Request|Internal Server Error|Method Not "
                   r"Allowed|Unprocessable (?:Entity|Content)|Too Many Requests|Bad Gateway|Service Unavailable|"
                   r"Gateway Timeout|Conflict|Payload Too Large|NOT_FOUND)?", re.I)
_CORS = re.compile(r"No '?Access-Control-Allow-Origin'? header[^.\n]*|blocked by CORS policy[^.\n]*", re.I)
_GIT = re.compile(r"^\s*(?:fatal|error|hint):\s*(.+)$", re.M | re.I)
_NPM = re.compile(r"^\s*npm (?:ERR!|error)\s+(?:code\s+(E[A-Z]+)|(.+))$", re.M)
_PHRASES = [  # well-known messages without an exception name
    re.compile(p, re.I) for p in (
        r"Hydration failed[^.\n]*", r"Failed to resolve import[^\n]*", r"Module not found:[^\n]*",
        r"Segmentation fault[^\n]*", r"command not found[^\n]*", r"permission denied[^\n]*",
        r"address already in use[^\n]*", r"is not recognized as an internal or external command[^\n]*",
        r"CUDA out of memory[^\n]*", r"Maximum update depth exceeded[^\n]*", r"Invalid hook call[^\n]*",
        r"Too many re-renders[^\n]*", r"Unexpected token[^\n]*", r"is not a function[^\n]*",
        r"Cannot find module[^\n]*", r"No module named[^\n]*", r"Can't resolve[^\n]*",
    )
]

# ---------------------------------------------------------------------- what is the learner's own (never searched)
# a Windows path's folders may contain spaces (C:\Users\John Smith\…); anything with a backslash left over goes too
_WIN_PATH = re.compile(r"[A-Za-z]:\\(?:[^\\\n'\"<>|:*?]+\\)*[^\\\s'\"<>|:*?]*|\\\\[^\s\\]+\\[^\s'\"<>|]*")
_BACKSLASHED = re.compile(r"\S*\\\S*")
_POSIX_PATH = re.compile(r"(?<![\w.])(?:~|\.{1,2})?(?:/[\w.@\-+]+){2,}/?")
_SLASHED = re.compile(r"\S+/\S+/\S+")  # what is left of a path with spaces ("Smith/Desktop/hack/data.csv")
_URL = re.compile(r"\b(?:https?|wss?|file|postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqps?)://[^\s'\"<>)]+", re.I)
_HOSTPORT = re.compile(r"\b(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d{2,5})?\b|\[?::1?\]?:\d{2,5}\b|:::\d{2,5}\b")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{2,5})?\b")
_IPV6 = re.compile(r"(?<![\w:])(?=[0-9A-Fa-f:]*[0-9A-Fa-f]{2})(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])")
# host names are theirs (db.xyz.supabase.co, my-cluster.ab1cd.mongodb.net, api.internal) — a few public ones stay
_HOST = re.compile(r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:com|net|org|io|dev|app|co|ai|cloud|internal|local|"
                   r"lan|corp|xyz|me|us|ru|de|uk|edu|gov|info|biz|tech|site|online|sh|gg|tv|so|fm|am|ly|it|es|fr|nl|ca|au|"
                   r"in|jp|cn|br|space|host|website|page|link|live|run|pro|one|world|studio|vercel\.app|herokuapp\.com)\b",
                   re.I)
_PUBLIC_HOSTS = {"socket.io", "github.com", "api.github.com", "pypi.org", "npmjs.com", "registry.npmjs.org",
                 "api.openai.com", "stackoverflow.com"}
_KEYVALUE = re.compile(r"\b(host|hostname|server|port|user|username|password|passwd|pwd|dbname|database|db|token|"
                       r"apikey|api_key|secret)\s*[=:]\s*['\"]?[^\s'\",)]+['\"]?", re.I)
_NAMEPORT = re.compile(r"\b[A-Za-z][\w-]*:\d{2,5}\b|(?<![\w:]):\d{2,5}\b|\bport\s+\d{2,5}\b", re.I)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_HEX = re.compile(r"\b0x[0-9a-fA-F]+\b")
_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_LONGNUM = re.compile(r"\b\d{5,}\b")
_LINECOL = re.compile(r"(?:line|ln|col)\s*\d+|:\d+:\d+\b|\(\d+,\s*\d+\)", re.I)
_KEYLIKE = re.compile(r"\b(?:sk|pk|rk|ghp|gho|ghs|xox[bpas]|AIza|AQ|hf|glpat|github_pat)[-_.A-Za-z0-9]{12,}\b|"
                      r"\beyJ[\w-]{6,}\.[\w-]{6,}\.[\w-]{6,}\b|\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
# any long token mixing letters and digits (a key, a secret, a session id) — error names have no digits
_ENTROPIC = re.compile(r"(?<![\w-])(?=[\w\-+/=]*\d)(?=[\w\-+/=]*[A-Za-z])[\w\-+/=]{20,}")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
# (an apostrophe inside a word — "Can't" — is not a quote)
_QUOTED = re.compile(r"(?<![A-Za-z])'([^'\n]{1,80})'(?![A-Za-z])|\"([^\"\n]{1,80})\"|`([^`\n]{1,80})`")
_OWN_FILE = re.compile(r"\b[\w\-]+\.(?:jsx?|tsx?|mjs|cjs|py|svelte|vue|java|kt|swift|go|rs|cpp|c|h|cs|rb|php|html|css)\b")
_INNER_MSG = re.compile(r"['\"]message['\"]\s*:\s*['\"]([^'\"]{3,200})['\"]")

_STOP = {"the", "a", "an", "is", "are", "was", "of", "to", "in", "on", "for", "at", "by", "with", "and", "or", "it",
         "this", "that", "be", "from", "as", "i", "my", "me", "we", "our", "you", "your", "when", "what", "how", "why",
         "does", "do", "did", "get", "got", "getting", "have", "has", "can", "cant", "can't", "cannot", "not", "no",
         "please", "help", "error", "errors", "issue", "problem", "stuck", "work", "working", "works", "doesn't",
         "dont", "don't", "won't", "wont", "keep", "keeps", "still", "again", "just", "trying", "try", "tried", "use",
         "using", "used", "run", "running", "into", "there", "some", "any", "all", "but", "if", "then", "so", "because",
         "app", "code", "file", "files", "line", "says", "said", "shows", "thing", "only", "also", "after", "before",
         "npm", "err", "pip", "added", "adding", "installed", "installing", "upgraded", "updated"}


_PHRASE_KINDS = {"failed to resolve import", "module not found", "cannot find module", "can't resolve",
                 "no module named"}
_NOT_PACKAGES = {"fails", "failed", "failing", "fail", "error", "errors", "keeps", "doesnt", "doesn't", "wont", "won't",
                 "is", "was", "not", "gives", "throws", "crashes", "hangs", "stuck", "command", "works", "worked", "then",
                 "and", "but", "with", "for", "on", "in", "the", "a", "it", "again", "still", "never", "always"}
# a package the learner mentions ("after I added react-leaflet") — checked, but "not found" is never said about it
_MENTIONED = re.compile(r"\b(?:added|installed|upgraded|updated|installing|adding|upgrading)\s+"
                        r"(@[\w.\-]+/[\w.\-]+|[a-z][\w.]*-[\w.\-]+)", re.I)


@dataclass
class Signature:
    """The searchable core of a roadblock."""

    kind: str  # the error's type ("ModuleNotFoundError", "ERESOLVE", "HTTP 422", "CORS") or "" if none was named
    message: str  # its core message, cleaned of the learner's own paths, hosts and numbers
    tags: list[str] = field(default_factory=list)  # Stack Overflow tags, most specific first
    ecosystem: str = ""  # "pypi" | "npm" | ""
    packages: list[str] = field(default_factory=list)  # packages it names (import names for Python)
    repos: list[str] = field(default_factory=list)  # the stack's GitHub repositories (issue search)
    local_import: str = ""  # an import of the learner's own file that did not resolve ("./Foo.svelte")
    node_builtin: str = ""  # a Node built-in module a browser bundle cannot resolve ("fs")
    words: list[str] = field(default_factory=list)  # distinctive words (relevance checks)
    mentioned: list[str] = field(default_factory=list)  # packages they mention having added (checked, never "not found")
    ran: list[str] = field(default_factory=list)  # commands they already ran ("npm install fails") — never searched

    @property
    def query(self) -> str:
        """The search text: the type and the core message, at most ~14 words."""
        text = f"{self.kind} {self.message}".strip() if self.kind and self.kind.lower() not in self.message.lower() \
            else self.message or self.kind
        words = text.split()[:14]
        while len(words) > 3 and words[-1].lower().strip(".,;:!?") in _STOP:
            words.pop()
        return " ".join(words)

    @property
    def title(self) -> str:
        head = f"{self.kind}: {self.message}" if self.kind and self.message and self.kind.lower() not in self.message.lower() \
            else (self.message or self.kind)
        return head[:140]

    def public(self) -> dict[str, object]:
        return {"kind": self.kind, "message": self.message, "query": self.query, "tags": self.tags,
                "ecosystem": self.ecosystem, "packages": self.packages, "repos": self.repos,
                "local_import": self.local_import, "node_builtin": self.node_builtin, "mentioned": self.mentioned}


def scrub(text: str) -> str:
    """The learner's own bits out: keys and secrets, URLs, e-mails, paths, IP addresses, host names, host:port and
    key=value settings, UUIDs, hex, long numbers. What is left is the error's wording."""
    t = _ANSI.sub("", text or "")
    t = _KEYLIKE.sub(" ", t)
    t = _URL.sub(" ", t)
    t = _EMAIL.sub(" ", t)
    t = _WIN_PATH.sub(" ", t)
    t = _BACKSLASHED.sub(" ", t)
    t = _POSIX_PATH.sub(" ", t)
    t = _SLASHED.sub(" ", t)
    t = _UUID.sub(" ", t)
    t = _ENTROPIC.sub(" ", t)
    t = _KEYVALUE.sub(lambda m: f" {m.group(1)} ", t)
    t = _HOSTPORT.sub(" ", t)
    t = _IPV4.sub(" ", t)
    t = _IPV6.sub(" ", t)
    t = _HOST.sub(lambda m: m.group(0) if m.group(0).lower() in _PUBLIC_HOSTS else " ", t)
    t = _NAMEPORT.sub(lambda m: " port " if m.group(0).lower().startswith("port") else " ", t)
    t = _HEX.sub(" ", t)
    t = _LINECOL.sub(" ", t)
    t = _LONGNUM.sub(" ", t)
    return re.sub(r"[ \t]+", " ", t)


def _clean_message(msg: str) -> str:
    inner = _INNER_MSG.search(msg or "")
    if inner:  # an API's JSON error body: its message is the error
        msg = inner.group(1)
    m = scrub(msg)
    m = re.sub(r"\bnpm (?:ERR!|error)\s*(?:code\s+E[A-Z]+\s*)?", " ", m)  # npm's log prefixes are not the message
    # what they did around it is not the error ("… after I added react-leaflet to my app")
    m = re.split(r"\s+(?:after|when|while|once|since|because|if|as soon as)\s+(?:i|we|my|our)\b", m, maxsplit=1,
                 flags=re.I)[0]
    m = re.sub(r"\s+at\s+(?:new\s+)?[\w$.<>]+\s*\(.*$|\s+at\s+\S+:\d+.*$", " ", m)  # a JavaScript stack
    m = _OWN_FILE.sub(" ", m)  # their own file names ("App.jsx")

    # quoted things: identifiers and package names stay; paths (theirs) go; a quoted sentence is usually the
    # error's own text, which is the point
    def keep(q: re.Match[str]) -> str:
        inner = next(g for g in q.groups() if g is not None).strip()
        if not inner:
            return " "
        if "/" in inner and not re.fullmatch(r"@[\w.\-]+/[\w.\-]+", inner):
            return " "
        if re.fullmatch(r"[\w@.\-+]{1,60}", inner) and not inner.startswith("."):
            return f"'{inner}'"
        return inner if len(inner.split()) >= 3 else " "
    m = _QUOTED.sub(keep, m)
    m = re.sub(r"\[type=[^\]]*\]|\binput_value=\S+|For further information visit\S*|[{}]|\(\s*\)", " ", m)
    m = re.sub(r"\b(?:from|in|at|to|of)\s*(?=[.,;:!?]|$)", " ", m)  # what pointed at a path that is gone
    for q in ('"', "'"):
        if m.count(q) % 2:  # a quote the learner opened or closed around the error — not part of it
            m = m.replace(q, " ") if q == '"' else re.sub(r"(?<![A-Za-z])'|'(?![A-Za-z])", " ", m)
    m = re.sub(r"\s+([.,;:!?])", r"\1", re.sub(r"\s+", " ", m)).strip(" .:;,-")
    return " ".join(m.split()[:16])


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z][a-z0-9+#.\-]*[a-z0-9+#]|[a-z]", text.lower())


def _tags_of(text: str) -> tuple[list[str], str, list[str]]:
    low = text.lower()
    toks = set(_tokens(low)) | set(re.findall(r"\b[\w.+-]+\b", low))
    hits: list[tuple[str, str, str]] = []
    for word, (tag, eco, repo) in STACK.items():
        if word in toks or (("." in word or "-" in word or "+" in word) and word in low):
            hits.append((tag, eco, repo))
    if "raspberry pi" in low:
        hits.append(("raspberry-pi", "", ""))
    if "traceback (most recent call last)" in low or re.search(r"\.py\b|\bpip install\b", low):
        hits.append(("python", "pypi", ""))
    if "node_modules" in low or re.search(r"\bnpm (?:err!|error)\b|\brequire\(|\.(?:mjs|cjs)\b", low):
        hits.append(("node.js", "npm", ""))
    if re.search(r"\.(?:jsx|tsx)\b", low):
        hits.append(("reactjs", "npm", "facebook/react"))
    elif re.search(r"\.ts\b", low):
        hits.append(("typescript", "npm", ""))
    elif re.search(r"\.js\b", low):
        hits.append(("javascript", "npm", ""))
    if "access-control-allow-origin" in low or "cors policy" in low:
        hits.append(("cors", "", ""))
    if re.search(r"\.svelte\b", low):
        hits.append(("svelte", "npm", "sveltejs/svelte"))
    tags: list[str] = []
    repos: list[str] = []
    ecos: list[str] = []
    for tag, eco, repo in hits:
        if tag not in tags:
            tags.append(tag)
        if repo and repo not in repos:
            repos.append(repo)
        if eco:
            ecos.append(eco)
    tags.sort(key=lambda t: t in _GENERIC_TAGS)  # the most specific first (stable otherwise)
    eco = sorted(set(ecos), key=lambda e: (-ecos.count(e), ecos.index(e)))[0] if ecos else ""  # ties: the first named
    return tags[:5], eco, repos[:2]


def _packages(text: str, eco: str) -> tuple[list[str], str, str, str]:
    """(packages, ecosystem, a local import that failed, a Node built-in the bundle cannot resolve)."""
    pkgs: list[str] = []
    local = builtin = ""
    for m in re.finditer(r"No module named '([\w.]+)'", text):
        pkgs.append(m.group(1) if m.group(1) in IMPORT_TO_PYPI else m.group(1).split(".")[0])
        eco = "pypi"
    for m in re.finditer(r"cannot import name '(\w+)' from '([\w.]+)'", text):
        pkgs.append(m.group(2).split(".")[0])
        eco = "pypi"
    for m in re.finditer(r"(?:Cannot find module|Can't resolve|Could not resolve|Failed to resolve import|"
                         r"Cannot find package)\s+['\"]([^'\"]+)['\"]", text):
        spec = m.group(1)
        if spec.startswith((".", "/", "$lib", "~", "@/")) or re.match(r"[A-Za-z]:\\", spec):
            local = local or spec.split("/")[-1][:60]
            continue
        spec = spec.removeprefix("node:")
        name = "/".join(spec.split("/")[:2]) if spec.startswith("@") else spec.split("/")[0]
        if name in NODE_BUILTINS:
            builtin = builtin or name
            continue
        pkgs.append(name)
        eco = eco or "npm"
    for m in re.finditer(r"\b(pip3?|npm|pnpm|yarn)\s+(?:install|i|add)\s+([@\w][\w@/.\-\[\]]*)(:?)", text):
        name = re.sub(r"\[.*\]$", "", m.group(2))
        if m.group(3) or name.lower() in _NOT_PACKAGES or name.startswith("-"):
            continue  # "npm install fails: …" is prose, not a package called "fails"
        pkgs.append(name)
        eco = eco or ("pypi" if m.group(1).startswith("pip") else "npm")
    seen: list[str] = []
    for p in pkgs:
        if p and p not in seen and len(p) <= 60:
            seen.append(p)
    return seen[:3], eco, local, builtin


# a command they already ran: an answer whose code only repeats it is not showing them a fix
_RAN_STOP = r"(?:fails?|failed|failing|gives?|gave|throws?|threw|returns?|says|shows|and|but|with|then|again|still|errors?|crash(?:es|ed)?|doesn|does|didn|did|is|was|in|on|for|to|of)"
_RAN = re.compile(
    r"(?<![\w-])((?:npm|pnpm|yarn|bun|npx|pip3?|python3?\s+-m\s+pip|uv\s+pip|uv|poetry|cargo|go|docker\s+compose|docker|git)"
    rf"(?:\s+(?!{_RAN_STOP}\b)[A-Za-z@\-][\w@./:=^~+\-]*){{1,4}})", re.I)


def ran_commands(clean: str) -> list[str]:
    """The commands in their (already scrubbed) text, lower-cased with single spaces."""
    out: list[str] = []
    for m in _RAN.finditer(clean):
        cmd = " ".join(m.group(1).lower().split())
        if cmd not in out:
            out.append(cmd)
    return out[:4]


def extract(text: str) -> Signature:
    """The signature of a roadblock described in words, pasted as a traceback, or both. The error's wording is read
    from the text AFTER the learner's own bits are gone (a port cannot survive as "the message after the colon")."""
    raw = _ANSI.sub("", text or "")
    clean = scrub(raw)
    kind = message = ""
    # Python: the traceback's LAST exception line is the one that matters
    module = ""
    py = [m for m in _PY_EXC.finditer(clean)]
    if py:
        m = py[-1]
        module, kind, message = (m.group(1) or ""), m.group(2), (m.group(3) or "")
        detail = re.search(r"^\s+(\S[^\n]*?)\s+\[type=(\w+)", clean[m.end():], re.M)
        if kind == "ValidationError" and detail:  # pydantic: the first failed field says what is wrong
            message = f"{detail.group(1)} ({detail.group(2).replace('_', ' ')})"
    if not kind:
        js = _JS_EXC.search(clean)
        if js:
            kind, message = js.group(1), js.group(2)
    if not kind and (cors := _CORS.search(clean)):
        kind, message = "CORS", cors.group(0)
    if not kind:
        npm = _NPM.search(clean)
        code = _CODE.search(clean)
        if npm and npm.group(1):
            kind = npm.group(1)
            rest = [x.group(2) for x in _NPM.finditer(clean) if x.group(2) and kind in x.group(2)]
            message = (rest[0].split(kind, 1)[-1] if rest else "")
        elif code:
            kind = code.group(1)
            after = clean[code.end():].split("\n", 1)[0]
            message = after.split(":", 1)[-1] if ":" in after else after
    if not kind and (http := _HTTP.search(clean)):
        kind = f"HTTP {http.group(1)}"
        message = (http.group(2) or "").replace("_", " ")
        if not message:  # "401 invalid token": the rest of the line says what it is about
            message = " ".join(clean[http.end():].split("\n", 1)[0].split()[:10])
    if not kind:
        git = _GIT.search(clean)
        phrase = next((p.search(clean) for p in _PHRASES if p.search(clean)), None)
        if phrase is not None:
            head = re.match(r"([A-Za-z][A-Za-z ']{3,40}?)(?::|\s+(?=['\"]|because|when|from|in\b))", phrase.group(0))
            if head and head.group(1).strip().lower() in _PHRASE_KINDS:
                kind, message = head.group(1).strip(), phrase.group(0)[head.end():]
            else:
                message = phrase.group(0)
        elif git is not None and re.search(r"\bgit\b|push|pull|merge|rebase|commit|refs?\b", clean, re.I):
            kind, message = "git", git.group(1)
    if not message and not kind:
        # plain words: the most technical sentence
        sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n+", clean) if s.strip()]
        scored = sorted(sentences, key=lambda s: -len(re.findall(r"[A-Za-z]+[A-Z_./()]\w*|\w+\(\)|<\w+>|\b\d{3}\b", s)))
        message = scored[0] if scored else clean
    message = _clean_message(message)
    tags, eco, repos = _tags_of(raw + " " + module.replace("_core", "").replace(".", " "))
    pkgs, eco2, local, builtin = _packages(raw, eco)
    eco = eco2 or eco
    if kind in ("ModuleNotFoundError", "ImportError") and "python" not in tags:
        tags.append("python")
    if kind == "git" and "git" not in tags:
        tags.append("git")
    words = [w for w in _tokens(f"{kind} {message}") if w not in _STOP and len(w) > 1]
    if kind.startswith("HTTP "):
        words = [w for w in words if w != "http"]  # its status code decides (relevance() requires it)
    if len(set(words)) < 3:  # a thin signature ("returns 500"): the stack must match too
        words += [w for t in tags for w in _tokens(t.replace("-", " ")) if w not in _STOP and len(w) > 1]
    mentioned = [m.group(1) for m in _MENTIONED.finditer(raw) if m.group(1) not in pkgs][:2]
    if mentioned and not eco:
        eco = "npm" if "npm" in raw.lower() or "node" in tags else ""
    return Signature(kind=kind, message=message, tags=tags, ecosystem=eco, packages=pkgs, repos=repos,
                     local_import=local, node_builtin=builtin, words=list(dict.fromkeys(words))[:12],
                     mentioned=mentioned, ran=ran_commands(clean))


def relevance(sig: Signature, text: str) -> float:
    """How much of the signature a candidate's text contains (0–1; the error type counts double)."""
    if not sig.words:
        return 0.0
    if sig.kind.startswith("HTTP ") and sig.kind[5:] not in re.findall(r"\b\d{3}\b", text or ""):
        return 0.0  # an HTTP error is about its status code: "how to make an HTTP request" is not a 500
    have = set(_tokens(text))
    kind = sig.kind.lower()
    score = weight = 0.0
    for w in sig.words:
        wt = 2.0 if w == kind or (kind and w in kind.split()) else 1.0
        weight += wt
        if w in have or (len(w) > 4 and w in text.lower()):
            score += wt
    return round(score / weight, 3) if weight else 0.0
