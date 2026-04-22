if [ -n "${HOME:-}" ] && [ -n "${PATH:-}" ]; then
  old_ifs=$IFS
  IFS=:
  new_path=

  for entry in $PATH; do
    [ "$entry" = "$HOME/AppImages" ] && continue
    if [ -n "$new_path" ]; then
      new_path=$new_path:$entry
    else
      new_path=$entry
    fi
  done

  IFS=$old_ifs
  PATH=$new_path
  export PATH
  unset entry new_path old_ifs
fi

unalias appimage-builder 2>/dev/null || true
