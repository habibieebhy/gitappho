# GitAppho v7 — installed wrapper
unalias gitappho 2>/dev/null || true
gitappho() { command python3 "$HOME/.config/gitappho/gitappho.py" "$@"; }
