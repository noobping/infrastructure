alias yq='podman run --rm -i \
  --userns=keep-id \
  --user $(id -u):$(id -g) \
  -v "$PWD:/work:Z" -w /work \
  docker.io/mikefarah/yq:latest'