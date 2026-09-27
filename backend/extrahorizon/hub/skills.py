"""Skills, roles and interests in one vocabulary: what people write on their card, what a search is tagged with and
what GitHub reports all become the same words, so "reactjs", "React.js" and a Stack Overflow tag "reactjs" meet."""

from __future__ import annotations

import re

SYNONYMS = {
    "js": "javascript", "ecmascript": "javascript", "ts": "typescript", "reactjs": "react", "react.js": "react",
    "nextjs": "next.js", "next": "next.js", "vuejs": "vue", "vue.js": "vue", "nuxt.js": "nuxt", "sveltekit": "svelte",
    "node": "node.js", "nodejs": "node.js", "expressjs": "express", "py": "python", "python3": "python",
    "golang": "go", "cpp": "c++", "csharp": "c#", "postgres": "postgresql", "psql": "postgresql", "mongo": "mongodb",
    "tf": "tensorflow", "torch": "pytorch", "sklearn": "scikit-learn", "cv": "computer vision", "cv2": "opencv",
    "ml": "machine learning", "machine-learning": "machine learning", "deep-learning": "deep learning",
    "ai": "machine learning", "llm": "llms", "llms": "llms", "genai": "llms", "openai-api": "openai",
    "nlp": "nlp", "ui": "design", "ux": "design", "ui/ux": "design", "ux/ui": "design", "product design": "design",
    "graphic design": "design", "tailwind-css": "tailwind", "tailwindcss": "tailwind", "amazon-web-services": "aws",
    "google-cloud-platform": "gcp", "unity-game-engine": "unity", "unity3d": "unity", "raspberry-pi": "raspberry pi",
    "raspberrypi": "raspberry pi", "esp-32": "esp32", "docker-compose": "docker", "react-native": "react native",
    "html5": "html", "css3": "css", "scss": "css", "sass": "css", "vue3": "vue", "k8s": "kubernetes",
    "public speaking": "pitch", "presentation": "pitch", "pitching": "pitch", "slides": "pitch",
    "project management": "product", "pm": "product", "websockets": "websocket", "rest": "api", "rest api": "api",
    "data viz": "data visualization", "dataviz": "data visualization", "d3": "data visualization",
    "stripe-payments": "stripe", "oauth-2.0": "oauth", "jupyter-notebook": "python", "jupyter notebook": "python",
    "hardware hacking": "hardware", "embedded": "hardware", "iot": "iot", "internet of things": "iot",
}

# a role someone is looking for → the skills that cover it
ROLES: dict[str, set[str]] = {
    "frontend": {"react", "svelte", "vue", "angular", "next.js", "javascript", "typescript", "html", "css", "tailwind"},
    "backend": {"python", "fastapi", "flask", "django", "node.js", "express", "go", "java", "spring-boot", "postgresql",
                "mongodb", "api", "rust", "c#"},
    "fullstack": {"react", "svelte", "vue", "next.js", "node.js", "python", "fastapi", "express", "django"},
    "design": {"design", "figma", "illustration", "accessibility"},
    "ml": {"machine learning", "deep learning", "pytorch", "tensorflow", "scikit-learn", "computer vision", "nlp",
           "llms", "opencv", "mediapipe"},
    "data": {"data visualization", "pandas", "sql", "postgresql", "python", "r", "numpy"},
    "mobile": {"flutter", "dart", "swift", "kotlin", "react native", "android", "ios", "expo"},
    "hardware": {"arduino", "esp32", "raspberry pi", "c++", "c", "hardware", "iot"},
    "devops": {"docker", "kubernetes", "aws", "gcp", "azure", "ci", "linux", "nginx", "vercel"},
    "game": {"unity", "godot", "c#", "three.js", "game dev"},
    "pitch": {"pitch", "product", "storytelling"},
    "product": {"product", "pitch", "research"},
}
ROLE_WORDS = {  # whole words (Russian stems end with *): "linux" is not UX, "scenarios" is not iOS
    "frontend": ("frontend", "front-end", "front end", "фронт*"),
    "backend": ("backend", "back-end", "back end", "бэк*", "бекенд*", "server side"),
    "fullstack": ("fullstack", "full-stack", "full stack", "фулстек*"),
    "design": ("designer", "designers", "design", "ui/ux", "ux", "дизайн*"),
    "ml": ("machine learning", "ml engineer", "ml", "ai", "data scientist", "машинн*", "нейросет*"),
    "data": ("data analyst", "data engineer", "data person", "аналитик*"),
    "mobile": ("mobile", "ios", "android", "flutter", "мобил*"),
    "hardware": ("hardware", "embedded", "arduino", "железо", "электрон*"),
    "devops": ("devops", "deploy person", "infra", "cloud"),
    "game": ("game dev", "gamedev", "unity dev", "игр*"),
    "pitch": ("pitch", "presenter", "presentation", "питч*", "презентац*"),
    "product": ("product manager", "pm", "product person"),
}
_ROLE_RE = {role: re.compile("|".join(
    (r"\b" + re.escape(w[:-1]) + r"\w*") if w.endswith("*") else (r"(?<![\w/])" + re.escape(w) + r"(?![\w/])")
    for w in words), re.I) for role, words in ROLE_WORDS.items()}
# GitHub's language names → skills
GITHUB_LANGUAGES = {
    "Python": "python", "Jupyter Notebook": "python", "JavaScript": "javascript", "TypeScript": "typescript",
    "Svelte": "svelte", "Vue": "vue", "HTML": "html", "CSS": "css", "SCSS": "css", "Java": "java", "Kotlin": "kotlin",
    "Swift": "swift", "Dart": "dart", "C++": "c++", "C": "c", "C#": "c#", "Go": "go", "Rust": "rust", "Ruby": "ruby",
    "PHP": "php", "Shell": "shell", "Solidity": "solidity", "R": "r", "MATLAB": "matlab", "GDScript": "godot",
    "Objective-C": "ios", "Astro": "astro",
}

_KNOWN = set(SYNONYMS.values()) | {s for v in ROLES.values() for s in v} | set(GITHUB_LANGUAGES.values())


def norm(skill: str) -> str:
    s = re.sub(r"\s+", " ", (skill or "").strip().lower())
    s = s.strip(" .,;:!?*")  # (C#, F#, C++ keep their sign)
    return SYNONYMS.get(s, s)


def norm_list(items: list[str] | str | None, limit: int = 12, width: int = 32) -> list[str]:
    if isinstance(items, str):
        items = re.split(r"[,;\n]+", items[:2000])
    out: list[str] = []
    for x in list(items or [])[:limit * 4]:
        n = norm(str(x)[:200])[:width]
        if n and n not in out:
            out.append(n)
            if len(out) >= limit:
                break
    return out


def roles_in(text: str) -> list[str]:
    """Roles a sentence asks for ("we need a frontend dev and a designer")."""
    low = (text or "").lower()
    return [role for role, rx in _ROLE_RE.items() if rx.search(low)]


def skills_in(text: str) -> list[str]:
    """Known skill words a sentence names ("someone who knows React and Figma")."""
    low = (text or "").lower()
    toks = set(re.findall(r"[a-z][a-z0-9+#.\-/]*[a-z0-9+#]|[a-z]", low))
    found: list[str] = []
    for word in sorted(toks | {w for w in SYNONYMS if " " in w and w in low}):
        n = norm(word)
        if n in _KNOWN and n not in found and n not in ("ai",):
            found.append(n)
    for multi in ("machine learning", "computer vision", "data visualization", "react native", "raspberry pi"):
        if multi in low and multi not in found:
            found.append(multi)
    return found[:10]


def covers(skills: set[str], need: str) -> bool:
    """Does a set of skills cover a need (a skill, or a role through its skills)?"""
    need = norm(need)
    if need in skills:
        return True
    return bool(ROLES.get(need, set()) & skills)
