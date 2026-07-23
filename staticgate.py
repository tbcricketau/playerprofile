"""staticgate — a StatiCrypt-equivalent password gate for a static site (no Node needed).

Encrypts each built HTML page with **AES-256-GCM**, the key derived from a shared password via
**PBKDF2-HMAC-SHA256**. The wrapped page ships only a password box + the ciphertext; the real
content is decrypted **in the browser** with the Web Crypto API (`crypto.subtle`), so view-source
shows only ciphertext. The password is remembered in `sessionStorage`, so a coach enters it once
and every linked report/vision page auto-decrypts.

NOT high security — it's a shared password for coaches/selectors to keep our own players out — but
it genuinely gates the content on public static hosting (unlike a JS `prompt`, which can't hide the
files). Reset the password by re-running the deploy with a new one.

    from staticgate import encrypt_dir
    encrypt_dir("site", password, title="AUS Scouting")   # encrypts site/**/*.html in place

Crypto params match Web Crypto exactly: PBKDF2 SHA-256 @ 200k iterations → 256-bit key; AES-GCM with
a 12-byte IV; the GCM tag is appended to the ciphertext (both `cryptography` and Web Crypto do this).
"""
import base64
import hashlib
import html as _html
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_ITER = 200_000
_MARKER = "<!--staticgate-->"   # so a re-run doesn't double-encrypt

_SHELL = """<!doctype html><!--staticgate--><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__</title>
<style>
 :root{color-scheme:light}
 body{font:15px/1.5 Inter,-apple-system,Segoe UI,sans-serif;background:#F5F7FA;color:#1a1a2e;margin:0}
 #gate{max-width:360px;margin:12vh auto 0;padding:26px 24px;background:#fff;border:1px solid #e5e7eb;
   border-radius:12px;box-shadow:0 1px 6px rgba(0,0,0,.06)}
 #gate h1{color:#003087;font-size:18px;margin:0 0 4px} #gate p{color:#6b7280;font-size:13px;margin:0 0 16px}
 #gate input{width:100%;box-sizing:border-box;padding:10px 12px;font-size:15px;border:1px solid #d5dced;border-radius:8px}
 #gate button{width:100%;margin-top:10px;padding:10px;font-size:15px;font-weight:600;color:#fff;background:#003087;
   border:0;border-radius:8px;cursor:pointer} #gate button:hover{background:#00246b}
 #gerr{color:#b91c1c;font-size:13px;margin-top:8px;display:none}
</style></head><body>
<div id="gate"><h1>__TITLE__</h1><p>Coaches &amp; selectors — enter the access password.</p>
<form id="gform"><input id="gpw" type="password" autofocus placeholder="Password" autocomplete="current-password">
<button type="submit">Enter</button><div id="gerr">Wrong password — try again.</div></form></div>
<script>
const D=__DATA__;
const b64=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
async function decrypt(pw){
  const km=await crypto.subtle.importKey("raw",new TextEncoder().encode(pw),"PBKDF2",false,["deriveKey"]);
  const key=await crypto.subtle.deriveKey({name:"PBKDF2",salt:b64(D.salt),iterations:D.iter,hash:"SHA-256"},
    km,{name:"AES-GCM",length:256},false,["decrypt"]);
  const pt=await crypto.subtle.decrypt({name:"AES-GCM",iv:b64(D.iv)},key,b64(D.ct));
  return new TextDecoder().decode(pt);
}
async function reveal(pw,remember){
  let h; try{ h=await decrypt(pw);}catch(e){ return false; }
  if(remember) try{ sessionStorage.setItem("sg_pw",pw);}catch(e){}
  document.open(); document.write(h); document.close(); return true;
}
document.getElementById("gform").addEventListener("submit",async e=>{
  e.preventDefault();
  const ok=await reveal(document.getElementById("gpw").value,true);
  if(!ok) document.getElementById("gerr").style.display="block";
});
(async()=>{ let s; try{ s=sessionStorage.getItem("sg_pw"); }catch(e){} if(s) await reveal(s,false); })();
</script></body></html>"""


def encrypt_html(html_str: str, password: str, title: str = "Scouting reports") -> str:
    salt, iv = os.urandom(16), os.urandom(12)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITER, 32)
    ct = AESGCM(key).encrypt(iv, html_str.encode("utf-8"), None)   # ciphertext || 16-byte GCM tag
    data = {"salt": base64.b64encode(salt).decode(), "iv": base64.b64encode(iv).decode(),
            "ct": base64.b64encode(ct).decode(), "iter": _ITER}
    return _SHELL.replace("__DATA__", json.dumps(data)).replace("__TITLE__", _html.escape(title))


def encrypt_dir(root: str, password: str, title: str = "Scouting reports") -> int:
    """Encrypt every .html under `root` in place (skips already-gated pages). Returns the count."""
    n = 0
    for dp, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != ".git"]
        for f in files:
            if not f.endswith(".html"):
                continue
            p = os.path.join(dp, f)
            s = open(p, encoding="utf-8").read()
            if _MARKER in s:                      # already encrypted (idempotent)
                continue
            open(p, "w", encoding="utf-8").write(encrypt_html(s, password, title))
            n += 1
    return n
