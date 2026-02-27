
if [ -f /usr/bin/todo ]; then
   status="$(passwd -S "$USER" 2>/dev/null | awk '{print $2}')"
   if [ "$status" = "NP" ] || [ "$status" = "L" ]; then
      /usr/bin/todo
   fi
fi
