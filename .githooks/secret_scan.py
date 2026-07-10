"""Pre-commit secret scan (stdlib only). Blocks the commit if staged additions look like
credentials. If it flags a false positive, fix the string (use an env var / gitignored
file / an obvious placeholder like <YOUR-KEY>) rather than bypassing the hook."""
import re
import subprocess
import sys

diff = subprocess.run(
    ["git", "diff", "--cached", "-U0"],
    capture_output=True, text=True, errors="replace",
).stdout
added = "\n".join(
    line[1:] for line in diff.splitlines()
    if line.startswith("+") and not line.startswith("+++")
)

PATTERNS = [
    (r"sk-ant-[A-Za-z0-9\-_]{20,}", "Anthropic API key"),
    (r"AccountKey=[A-Za-z0-9+/=]{40,}", "Azure storage account key"),
    (r"SharedAccessSignature=sv[=]", "Azure SAS token (connection string)"),
    # A SAS on a blob URL — the form `video.py` bakes into report/player pages. `sig=` is the
    # signature itself, so it is unmistakable, and matching it catches the query-string SAS
    # that the connection-string pattern above misses entirely. Percent-encoding is normal.
    (r"[?&]sig=[A-Za-z0-9%+/=]{30,}", "Azure SAS token (blob URL)"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key block"),
    (r"eyJ[A-Za-z0-9_\-]{20,}\.eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}", "JWT"),
    (r"ghp_[A-Za-z0-9]{30,}", "GitHub token (classic)"),
    (r"github_pat_[A-Za-z0-9_]{30,}", "GitHub token (fine-grained)"),
    (r"(?i)\b(app_secret|client_secret|api[_-]?key|access[_-]?token|password)\b\s*[=:]\s*"
     r"['\"][A-Za-z0-9+/=\-_.~%]{16,}['\"]", "credential literal"),
]

hits = []
for pat, label in PATTERNS:
    for m in re.finditer(pat, added):
        frag = m.group(0)
        if any(p in frag for p in ("<", "...", "xxx", "XXX", "example", "placeholder")):
            continue  # obvious placeholder
        hits.append((label, frag[:14] + "..."))

if hits:
    print("COMMIT BLOCKED - possible secrets in staged changes:")
    for label, frag in hits:
        print(f"  {label}: {frag}")
    print("Secrets belong in env vars or gitignored files (.env / .streamlit/secrets.toml).")
    print("See c:\\Projects\\README.md section 4 (Credentials).")
    sys.exit(1)
sys.exit(0)
