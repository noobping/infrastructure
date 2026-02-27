
if command -v todo >/dev/null 2>&1 &&
   command -v passwd >/dev/null 2>&1 &&
   [ "$(passwd -S "$USER" 2>/dev/null | awk '{print $2}')" = "NP" ]; then
   todo
fi
