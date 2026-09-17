# Build and publish the stable image graph for AMD64 and ARM64.
stable:
    @{{ quote(just_executable()) }} online::_images stable both

# Build and publish the experimental FCOS next image graph.
next:
    @{{ quote(just_executable()) }} online::_images next both

# Build online installers and every Ignition configuration.
media:
    @{{ quote(just_executable()) }} online::_media both

# Publish the online installers to the continuous GitHub release.
release:
    @{{ quote(just_executable()) }} online::_release

# Publish already-built online installers without rebuilding them.
release-assets:
    @{{ quote(just_executable()) }} online::_release

# Publish one built installer to GitLab's Generic Package Registry.
gitlab-media-publish:
    @{{ quote(just_executable()) }} online::_gitlab_media_publish

# Publish links for the built installers as a GitLab release.
gitlab-release-assets:
    @{{ quote(just_executable()) }} online::_gitlab_release

# Build one run-scoped image selected by the build environment.
image-task:
    #!/usr/bin/env bash
    set -euo pipefail
    stream="${BUILD_STREAM:?BUILD_STREAM is required}"
    architecture="${BUILD_ARCHITECTURE:?BUILD_ARCHITECTURE is required}"
    image="${BUILD_IMAGE_NAME:?BUILD_IMAGE_NAME is required}"
    just={{ quote(just_executable()) }}
    exec "$just" online::_images "$stream" "$architecture" "$image"

# Publish one multi-architecture image selected by the build environment.
manifest-task:
    #!/usr/bin/env bash
    set -euo pipefail
    stream="${BUILD_STREAM:?BUILD_STREAM is required}"
    image="${BUILD_IMAGE_NAME:?BUILD_IMAGE_NAME is required}"
    just={{ quote(just_executable()) }}
    exec "$just" online::_images "$stream" manifests "$image"

# Publish one GitLab manifest only while this is the default-branch revision.
gitlab-manifest-task:
    #!/usr/bin/env bash
    set -euo pipefail
    : "${CI_API_V4_URL:?CI_API_V4_URL is required}"
    : "${CI_COMMIT_SHA:?CI_COMMIT_SHA is required}"
    : "${CI_DEFAULT_BRANCH:?CI_DEFAULT_BRANCH is required}"
    : "${CI_JOB_TOKEN:?CI_JOB_TOKEN is required}"
    : "${CI_PROJECT_ID:?CI_PROJECT_ID is required}"
    encoded_branch="$(jq -rn --arg value "$CI_DEFAULT_BRANCH" '$value | @uri')"
    branch_sha="$(curl --fail-with-body --silent --show-error --location \
        --header "JOB-TOKEN: $CI_JOB_TOKEN" \
        "$CI_API_V4_URL/projects/$CI_PROJECT_ID/repository/commits/$encoded_branch" |
        jq -r '.id')"
    if [[ "$branch_sha" != "$CI_COMMIT_SHA" ]]; then
        echo "Skipping stale manifest for $CI_COMMIT_SHA; $CI_DEFAULT_BRANCH is at $branch_sha."
        exit 0
    fi
    just={{ quote(just_executable()) }}
    exec "$just" online::manifest-task

# Verify every staged image digest before any public tag is changed.
manifest-preflight:
    #!/usr/bin/env bash
    set -euo pipefail
    stream="${BUILD_STREAM:?BUILD_STREAM is required}"
    just={{ quote(just_executable()) }}
    exec "$just" online::_images "$stream" preflight all

# Build one installer selected by the build environment.
media-task:
    #!/usr/bin/env bash
    set -euo pipefail
    architecture="${BUILD_ARCHITECTURE:?BUILD_ARCHITECTURE is required}"
    profile="${BUILD_PROFILE:?BUILD_PROFILE is required}"
    just={{ quote(just_executable()) }}
    exec "$just" online::_media "$architecture" "$profile"

[private]
_images stream architecture="both" selection="all":
    #!/usr/bin/env bash
    set -euo pipefail

    repo={{ quote(justfile_directory()) }}
    stream={{ quote(stream) }}
    architecture={{ quote(architecture) }}
    selection={{ quote(selection) }}
    namespace="${IMAGE_NAMESPACE:-ghcr.io/noobping}"
    isolation="${BUILDAH_ISOLATION:-chroot}"
    tmpdir="${TMPDIR:-/tmp}"
    source_url="${SOURCE_URL:-$(git -C "$repo" config --get remote.origin.url || printf '%s' "$repo")}"
    revision="${REVISION:-$(git -C "$repo" rev-parse HEAD)}"
    if [[ -n "${PIPELINE_RUN_ID:-}" ]]; then
        run_id="$PIPELINE_RUN_ID"
    elif [[ -n "${GITHUB_RUN_ID:-}" ]]; then
        run_id="${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT:-1}"
    else
        run_id="local-${revision:0:12}-$(date +%s)-$$-${RANDOM}"
    fi
    run_id="$(printf '%s' "$run_id" | tr -c '[:alnum:]_.-' '-')"
    state_dir="$repo/dist/online/state/$stream/$run_id"
    registry_auth_dir=

    cleanup_registry_auth() {
        if [[ -n "$registry_auth_dir" ]]; then
            rm -f -- "$registry_auth_dir/config.json"
            rmdir -- "$registry_auth_dir" 2>/dev/null || true
        fi
    }
    trap cleanup_registry_auth EXIT

    case "$stream" in
        stable)
            fcos_stream=stable
            public_tag=latest
            arch_suffix=
            all_image_names=(ips policy workstation sway nas vm k3s minecraft jellyfin)
            ;;
        next)
            fcos_stream=next
            public_tag=next
            arch_suffix=-next
            all_image_names=(ips policy workstation sway)
            ;;
        *)
            echo "unsupported online stream: $stream" >&2
            exit 2
            ;;
    esac

    if [[ "$selection" == all ]]; then
        image_names=("${all_image_names[@]}")
    else
        selection_supported=false
        for image_name in "${all_image_names[@]}"; do
            if [[ "$selection" == "$image_name" ]]; then
                selection_supported=true
                break
            fi
        done
        if [[ "$selection_supported" != true ]]; then
            echo "unsupported $stream image selection: $selection" >&2
            exit 2
        fi
        image_names=("$selection")
    fi

    case "$architecture" in
        both|amd64|arm64|manifests|preflight) ;;
        *)
            echo "unsupported online architecture: $architecture" >&2
            echo "expected both, amd64, arm64, manifests, or preflight" >&2
            exit 2
            ;;
    esac

    registry="${namespace%%/*}"
    if [[ -n "${REGISTRY_TLS_VERIFY:-}" ]]; then
        tls_verify="$REGISTRY_TLS_VERIFY"
    else
        case "$registry" in
            localhost|localhost:*|127.0.0.1|127.0.0.1:*) tls_verify=false ;;
            *) tls_verify=true ;;
        esac
    fi
    if [[ -n "${SIGN_IMAGES:-}" ]]; then
        sign_images="$SIGN_IMAGES"
    else
        case "$registry" in
            localhost|localhost:*|127.0.0.1|127.0.0.1:*) sign_images=false ;;
            *) sign_images=true ;;
        esac
    fi

    run_podman() {
        if command -v podman >/dev/null 2>&1; then
            podman "$@"
        elif command -v flatpak-spawn >/dev/null 2>&1; then
            flatpak-spawn --host podman "$@"
        else
            echo "podman is required to build multi-architecture images" >&2
            exit 1
        fi
    }

    run_buildah() {
        if command -v buildah >/dev/null 2>&1; then
            TMPDIR="$tmpdir" buildah "$@"
        elif command -v flatpak-spawn >/dev/null 2>&1; then
            flatpak-spawn --host env TMPDIR="$tmpdir" buildah "$@"
        else
            echo "buildah is required to build and publish images" >&2
            exit 1
        fi
    }

    run_skopeo() {
        if command -v skopeo >/dev/null 2>&1; then
            skopeo "$@"
        elif command -v flatpak-spawn >/dev/null 2>&1 \
            && flatpak-spawn --host sh -lc 'command -v skopeo >/dev/null 2>&1'; then
            flatpak-spawn --host skopeo "$@"
        else
            echo "skopeo is required to publish split-runner manifests" >&2
            exit 1
        fi
    }

    run_cosign() {
        if command -v cosign >/dev/null 2>&1; then
            cosign "$@"
        elif command -v flatpak-spawn >/dev/null 2>&1 \
            && flatpak-spawn --host sh -lc 'command -v cosign >/dev/null 2>&1'; then
            flatpak-spawn --host cosign "$@"
        else
            echo "cosign is required when SIGN_IMAGES=true" >&2
            exit 1
        fi
    }

    check_boolean() {
        case "$2" in
            true|false) ;;
            *)
                printf '%s must be true or false; got %s\n' "$1" "$2" >&2
                exit 2
                ;;
        esac
    }

    native_architecture() {
        case "$(uname -m)" in
            x86_64) printf '%s\n' amd64 ;;
            aarch64|arm64) printf '%s\n' arm64 ;;
            *)
                echo "online builds do not support $(uname -m)" >&2
                exit 1
                ;;
        esac
    }

    check_arch_runtime() {
        local requested_arch="$1"
        local expected actual

        if [[ "$requested_arch" == "$native_arch" ]]; then
            return 0
        fi
        case "$requested_arch" in
            amd64) expected=x86_64 ;;
            arm64) expected=aarch64 ;;
        esac
        printf 'Checking %s container emulation...\n' "$requested_arch"
        if ! actual="$(run_podman run --rm --pull=missing \
            --arch "$requested_arch" \
            quay.io/fedora/fedora-minimal:latest uname -m)"; then
            echo "cannot execute $requested_arch containers" >&2
            echo "enable QEMU/binfmt or build on a native machine" >&2
            exit 1
        fi
        if [[ "$actual" != "$expected" ]]; then
            printf 'expected %s emulation, got %s\n' "$expected" "$actual" >&2
            exit 1
        fi
    }

    run_parallel() {
        local task index failed=0
        local -a tasks=("$@")
        local -a pids=()

        for task in "${tasks[@]}"; do
            "$task" &
            pids+=("$!")
        done
        for index in "${!pids[@]}"; do
            if ! wait "${pids[$index]}"; then
                printf 'online task failed: %s\n' "${tasks[$index]}" >&2
                failed=1
            fi
        done
        (( failed == 0 ))
    }

    build_image() {
        local context="$1"
        local name="$2"
        local image="${namespace}/${name}:${stage_tag}"
        local digest_file="$state_dir/${name}-${image_arch}.digest"
        shift 2

        printf '\n==> Building %s\n' "$image"
        run_buildah bud \
            --layers \
            --pull=always \
            --arch "$image_arch" \
            --isolation="$isolation" \
            --tls-verify="$tls_verify" \
            -t "$image" \
            --label "org.opencontainers.image.source=${source_url}" \
            --label "org.opencontainers.image.revision=${revision}" \
            "$@" \
            "$context"
        run_buildah push --tls-verify="$tls_verify" \
            --digestfile "$digest_file" \
            "$image" "docker://$image"
        tr -d '\r\n' < "$digest_file" | grep -Eq '^sha256:[0-9a-f]{64}$'
    }

    build_ips() {
        build_image images/ips ips --build-arg "FCOS_STREAM=${fcos_stream}"
    }

    build_policy() {
        build_image images/policy policy \
            --build-arg "POLICY_VERSION=${revision}"
    }

    build_workstation() {
        build_image images/workstation workstation \
            --build-arg "IMAGE_NAMESPACE=${namespace}" \
            --build-arg "POLICY_IMAGE=${namespace}/policy:${stage_tag}" \
            --build-arg "TAG=${stage_tag}"
    }

    build_sway() {
        build_image images/sway sway \
            --build-arg "IMAGE_NAMESPACE=${namespace}" \
            --build-arg "TAG=${stage_tag}"
    }

    build_nas() {
        build_image images/nas nas \
            --build-arg "IMAGE_NAMESPACE=${namespace}" \
            --build-arg "POLICY_IMAGE=${namespace}/policy:${stage_tag}" \
            --build-arg "TAG=${stage_tag}"
    }

    build_vm() {
        build_image vms/vm vm \
            --build-arg "IMAGE_NAMESPACE=${namespace}" \
            --build-arg "TAG=${stage_tag}"
    }

    build_k3s() {
        build_image vms/k3s k3s \
            --build-arg "IMAGE_NAMESPACE=${namespace}" \
            --build-arg "TAG=${stage_tag}"
    }

    build_minecraft() {
        build_image vms/minecraft minecraft \
            --build-arg "IMAGE_NAMESPACE=${namespace}" \
            --build-arg "TAG=${stage_tag}"
    }

    build_jellyfin() {
        build_image vms/jellyfin jellyfin \
            --build-arg "IMAGE_NAMESPACE=${namespace}" \
            --build-arg "TAG=${stage_tag}"
    }

    build_workstation_branch() {
        build_workstation
        build_sway
    }

    build_vm_branch() {
        build_vm
        run_parallel build_k3s build_minecraft build_jellyfin
    }

    build_architecture() {
        image_arch="$1"
        stage_tag="${image_arch}-${stream}-run-${run_id}"
        printf '\n========== Building %s %s %s ==========\n' \
            "$stream" "$image_arch" "$selection"
        case "$selection" in
            all)
                run_parallel build_ips build_policy
                if [[ "$stream" == stable ]]; then
                    run_parallel build_workstation_branch build_nas build_vm_branch
                else
                    build_workstation_branch
                fi
                ;;
            ips) build_ips ;;
            policy) build_policy ;;
            workstation) build_workstation ;;
            sway) build_sway ;;
            nas) build_nas ;;
            vm) build_vm ;;
            k3s) build_k3s ;;
            minecraft) build_minecraft ;;
            jellyfin) build_jellyfin ;;
        esac
    }

    build_amd64() {
        build_architecture amd64
    }

    build_arm64() {
        build_architecture arm64
    }

    promote_architecture() {
        local name="$1"
        local architecture="$2"
        local stage="${architecture}-${stream}-run-${run_id}"
        local source="${namespace}/${name}:${stage}"
        local destination="${namespace}/${name}:${architecture}${arch_suffix}"
        local digest_file="$state_dir/${name}-${architecture}-public.digest"

        printf '\n==> Publishing %s\n' "$destination"
        run_buildah manifest rm "$destination" >/dev/null 2>&1 || true
        run_buildah rmi "$destination" >/dev/null 2>&1 || true
        run_buildah tag "$source" "$destination"
        run_buildah push --tls-verify="$tls_verify" \
            --digestfile "$digest_file" \
            "$destination" "docker://$destination"
        tr -d '\r\n' < "$digest_file" | grep -Eq '^sha256:[0-9a-f]{64}$'
    }

    promote_remote_architecture() {
        local name="$1"
        local architecture="$2"
        local digest
        local destination="${namespace}/${name}:${architecture}${arch_suffix}"

        digest="$(tr -d '\r\n' \
            < "$state_dir/${name}-${architecture}.digest")"
        printf '\n==> Publishing %s\n' "$destination"
        run_skopeo copy \
            --src-tls-verify="$tls_verify" \
            --dest-tls-verify="$tls_verify" \
            "docker://${namespace}/${name}@${digest}" \
            "docker://$destination"
    }

    preflight_digests() {
        local verify_remote="${1:-false}"
        local name architecture digest digest_file
        local actual_architecture architecture_format

        architecture_format="$(printf '\173\173.Architecture\175\175')"

        for name in "${image_names[@]}"; do
            for architecture in amd64 arm64; do
                digest_file="$state_dir/${name}-${architecture}.digest"
                if [[ ! -s "$digest_file" ]]; then
                    echo "missing image digest: $digest_file" >&2
                    exit 1
                fi
                digest="$(tr -d '\r\n' < "$digest_file")"
                if [[ ! "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
                    echo "invalid image digest in $digest_file" >&2
                    exit 1
                fi
                if [[ "$verify_remote" == true ]]; then
                    actual_architecture="$(run_skopeo inspect \
                        --tls-verify="$tls_verify" \
                        --format "$architecture_format" \
                        "docker://${namespace}/${name}@${digest}")"
                    if [[ "$actual_architecture" != "$architecture" ]]; then
                        printf 'expected %s for %s, got %s\n' \
                            "$architecture" "$name" "$actual_architecture" >&2
                        exit 1
                    fi
                fi
            done
        done
    }

    publish_manifest() {
        local name="$1"
        local destination="${namespace}/${name}:${public_tag}"
        local local_manifest="localhost/pipeline-${name}:${stream}-${run_id}"
        local digest_file="$state_dir/${name}-${public_tag}.digest"
        local architecture digest

        run_buildah manifest rm "$local_manifest" >/dev/null 2>&1 || true
        run_buildah manifest create "$local_manifest"
        for architecture in amd64 arm64; do
            digest="$(tr -d '\r\n' \
                < "$state_dir/${name}-${architecture}.digest")"
            [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]
            run_buildah manifest add --tls-verify="$tls_verify" \
                "$local_manifest" "docker://${namespace}/${name}@${digest}"
        done

        printf '\n==> Publishing multi-architecture %s\n' "$destination"
        run_buildah manifest push --all --tls-verify="$tls_verify" \
            --digestfile "$digest_file" \
            "$local_manifest" "docker://$destination"
        run_buildah manifest rm "$local_manifest" >/dev/null
        digest="$(tr -d '\r\n' < "$digest_file")"
        [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]
        if [[ "$sign_images" == true ]]; then
            run_cosign sign --yes --recursive "${namespace}/${name}@${digest}"
        fi
    }

    check_boolean REGISTRY_TLS_VERIFY "$tls_verify"
    check_boolean SIGN_IMAGES "$sign_images"
    case "$registry" in
        localhost|localhost:*|127.0.0.1|127.0.0.1:*) ;;
        *)
            if [[ "${PUBLISH:-false}" != true ]]; then
                echo "set PUBLISH=true to update images in $registry" >&2
                exit 2
            fi
            if [[ "${ALLOW_DIRTY:-false}" != true ]] \
                && [[ -n "$(git -C "$repo" status --short --untracked-files=normal)" ]]; then
                echo "refusing to publish images from a dirty checkout" >&2
                echo "commit the changes or set ALLOW_DIRTY=true" >&2
                exit 2
            fi
            ;;
    esac
    if [[ "$sign_images" == true \
        && ( "$architecture" == both || "$architecture" == manifests ) ]]; then
        run_cosign version >/dev/null
    fi

    cd "$repo"
    mkdir -p "$state_dir"
    command -v flock >/dev/null 2>&1 || {
        echo "flock is required to coordinate online image builds" >&2
        exit 1
    }
    exec 9>"dist/online/.images-${stream}.lock"
    if ! flock -n 9; then
        echo "another $stream image build is already running in $repo" >&2
        exit 1
    fi

    registry_token="${REGISTRY_TOKEN:-${GITHUB_TOKEN:-}}"
    registry_user="${REGISTRY_USER:-${GITHUB_ACTOR:-}}"
    if [[ -n "$registry_token" ]]; then
        if [[ -z "$registry_user" ]]; then
            echo "REGISTRY_USER or GITHUB_ACTOR is required with a registry token" >&2
            exit 1
        fi
        registry_auth_dir="$(mktemp -d \
            "$repo/dist/online/.registry-auth.XXXXXXXXXX")"
        chmod 0700 "$registry_auth_dir"
        export DOCKER_CONFIG="$registry_auth_dir"
        export REGISTRY_AUTH_FILE="$registry_auth_dir/config.json"
        printf '%s' "$registry_token" \
            | run_buildah login --authfile "$REGISTRY_AUTH_FILE" \
                --tls-verify="$tls_verify" \
                --username "$registry_user" --password-stdin "$registry"
        chmod 0600 "$REGISTRY_AUTH_FILE"
    fi

    if [[ "$architecture" == manifests ]]; then
        preflight_digests true
        for name in "${image_names[@]}"; do
            promote_remote_architecture "$name" amd64
            promote_remote_architecture "$name" arm64
        done
        for name in "${image_names[@]}"; do
            publish_manifest "$name"
        done
        printf '\nPublished %s %s multi-architecture manifest(s) to %s.\n' \
            "$stream" "$selection" "$namespace"
        exit 0
    fi

    if [[ "$architecture" == preflight ]]; then
        preflight_digests true
        printf '\nVerified every %s staged image digest.\n' "$stream"
        exit 0
    fi

    native_arch="$(native_architecture)"
    case "$architecture" in
        both)
            check_arch_runtime amd64
            check_arch_runtime arm64
            run_parallel build_amd64 build_arm64
            build_arches=(amd64 arm64)
            ;;
        amd64)
            check_arch_runtime amd64
            build_amd64
            build_arches=(amd64)
            ;;
        arm64)
            check_arch_runtime arm64
            build_arm64
            build_arches=(arm64)
            ;;
    esac

    if [[ "$architecture" == both ]]; then
        preflight_digests false
        for name in "${image_names[@]}"; do
            for image_arch in "${build_arches[@]}"; do
                promote_architecture "$name" "$image_arch"
            done
            publish_manifest "$name"
        done
        printf '\nPublished %s %s images for AMD64 and ARM64 to %s.\n' \
            "$stream" "$selection" "$namespace"
    else
        printf '\nBuilt and staged %s %s %s image(s) at %s.\n' \
            "$stream" "$architecture" "$selection" "$namespace"
    fi

[private]
_media architecture="both" profile="all":
    #!/usr/bin/env bash
    set -euo pipefail

    repo={{ quote(justfile_directory()) }}
    architecture={{ quote(architecture) }}
    selected_profile={{ quote(profile) }}
    namespace="${IMAGE_NAMESPACE:-ghcr.io/noobping}"
    output="$repo/dist/online"

    run_podman() {
        if command -v podman >/dev/null 2>&1; then
            podman "$@"
        elif command -v flatpak-spawn >/dev/null 2>&1; then
            flatpak-spawn --host podman "$@"
        else
            echo "podman is required to build installer media" >&2
            exit 1
        fi
    }

    run_yq() {
        if command -v yq >/dev/null 2>&1; then
            yq "$@"
        elif command -v flatpak-spawn >/dev/null 2>&1 \
            && flatpak-spawn --host sh -lc 'command -v yq >/dev/null 2>&1'; then
            flatpak-spawn --host yq "$@"
        else
            run_podman run --rm \
                -v "$repo:/work:z" -w /work \
                docker.io/mikefarah/yq:4.45.1 "$@"
        fi
    }

    run_parallel() {
        local task index failed=0
        local -a tasks=("$@")
        local -a pids=()

        for task in "${tasks[@]}"; do
            "$task" &
            pids+=("$!")
        done
        for index in "${!pids[@]}"; do
            if ! wait "${pids[$index]}"; then
                printf 'media task failed: %s\n' "${tasks[$index]}" >&2
                failed=1
            fi
        done
        (( failed == 0 ))
    }

    render_butane() {
        local input="$1"
        local output_file="$2"
        local bootc_image="$3"

        sed \
            -e "s#__IMAGE_NAMESPACE__#${namespace}#g" \
            -e "s#__BOOTC_IMAGE__#${bootc_image}#g" \
            "$input" > "$output_file"
    }

    build_ignition() {
        local input="$1"
        local output_file="$2"

        run_podman run --rm --pull=never \
            -v "$repo:/work:z" -w /work \
            quay.io/coreos/butane:release \
            --pretty --strict --files-dir . "$input" \
            > "$output_file"
        run_podman run --rm -i --pull=never \
            quay.io/coreos/ignition-validate:release \
            - < "$output_file"
    }

    render_profile() {
        local profile="$1"
        local source_profile="$2"

        run_yq ea '. as $item ireduce ({}; . *+ $item)' \
            butane/base.yml \
            butane/updates.yml \
            "butane/${source_profile}.yml" \
            > "$output/butane/${profile}.bu"
        render_butane \
            "$output/butane/${profile}.bu" \
            "$output/butane/${profile}.rendered.bu" \
            "$profile"
        build_ignition \
            "dist/online/butane/${profile}.rendered.bu" \
            "$output/ign/${profile}.ign"
    }

    render_guest() {
        local guest="$1"

        run_yq ea '. as $item ireduce ({}; . *+ $item)' \
            butane/base.yml \
            butane/updates.yml \
            butane/vm.yml \
            "butane/${guest}.yml" \
            > "$output/butane/${guest}.bu"
        render_butane \
            "$output/butane/${guest}.bu" \
            "$output/butane/${guest}.rendered.bu" \
            "$guest"
        build_ignition \
            "dist/online/butane/${guest}.rendered.bu" \
            "$output/ign/${guest}.ign"
    }

    build_architecture_media() {
        local coreos_arch="$1"
        local base_iso profile out_iso

        run_podman run --rm --pull=never \
            --userns=keep-id \
            --user "$(id -u):$(id -g)" \
            -v "$repo:/work:z" -w /work \
            quay.io/coreos/coreos-installer:release \
            download -s stable -a "$coreos_arch" -p metal -f iso \
                -C /work/dist/online/cache --decompress
        base_iso="$(
            find dist/online/cache -maxdepth 1 -type f \
                -name "fedora-coreos-*-live-iso.${coreos_arch}.iso" \
                -printf '%f\n' \
                | LC_ALL=C sort -V \
                | tail -n 1
        )"
        if [[ -z "$base_iso" ]]; then
            echo "coreos-installer did not produce a $coreos_arch ISO" >&2
            exit 1
        fi
        base_iso="dist/online/cache/$base_iso"

        for profile in "${media_profiles[@]}"; do
            out_iso="dist/online/iso/${profile}-${coreos_arch}.iso"
            printf '\n==> Building %s\n' "$out_iso"
            rm -f "$out_iso" "${out_iso}.sha256"
            run_podman run --rm --pull=never \
                --userns=keep-id \
                --user "$(id -u):$(id -g)" \
                -v "$repo:/work:z" -w /work \
                quay.io/coreos/coreos-installer:release \
                iso customize \
                    --live-ignition dist/online/ign/setup.ign \
                    --dest-ignition "dist/online/ign/${profile}.ign" \
                    --pre-install butane/bin/detect-device \
                    -o "$out_iso" \
                    "$base_iso"
            (
                cd "$output/iso"
                sha256sum "${profile}-${coreos_arch}.iso" \
                    > "${profile}-${coreos_arch}.iso.sha256"
            )
        done
    }

    build_x86_64_media() {
        build_architecture_media x86_64
    }

    build_aarch64_media() {
        build_architecture_media aarch64
    }

    cd "$repo"
    case "$architecture" in
        both|amd64|arm64) ;;
        *)
            echo "unsupported media architecture: $architecture" >&2
            echo "expected both, amd64, or arm64" >&2
            exit 2
            ;;
    esac
    case "$selected_profile" in
        all) media_profiles=(nas workstation sway) ;;
        nas|workstation|sway) media_profiles=("$selected_profile") ;;
        *)
            echo "unsupported media profile: $selected_profile" >&2
            echo "expected all, nas, workstation, or sway" >&2
            exit 2
            ;;
    esac
    mkdir -p "$output/butane" "$output/cache" "$output/ign" "$output/iso"
    command -v flock >/dev/null 2>&1 || {
        echo "flock is required to coordinate media builds" >&2
        exit 1
    }
    exec 9>"$output/.media.lock"
    if ! flock -n 9; then
        echo "another online media build is already running in $repo" >&2
        exit 1
    fi

    run_podman pull --quiet quay.io/coreos/butane:release >/dev/null
    run_podman pull --quiet quay.io/coreos/ignition-validate:release >/dev/null
    run_podman pull --quiet quay.io/coreos/coreos-installer:release >/dev/null

    run_yq ea '. as $item ireduce ({}; . *+ $item)' \
        butane/base.yml \
        butane/setup.yml \
        > "$output/butane/setup.bu"
    render_butane \
        "$output/butane/setup.bu" \
        "$output/butane/setup.rendered.bu" \
        workstation
    build_ignition \
        dist/online/butane/setup.rendered.bu \
        "$output/ign/setup.ign"

    render_profile nas nas
    render_profile workstation workstation
    render_profile sway workstation
    render_guest k3s
    render_guest minecraft
    render_guest jellyfin

    case "$architecture" in
        both) run_parallel build_x86_64_media build_aarch64_media ;;
        amd64) build_x86_64_media ;;
        arm64) build_aarch64_media ;;
    esac

    printf '\nBuilt %s %s online Ignition and installer artifacts in %s.\n' \
        "$architecture" "$selected_profile" "$output"

[private]
_release:
    #!/usr/bin/env bash
    set -euo pipefail

    repo={{ quote(justfile_directory()) }}
    release_repo="${RELEASE_REPOSITORY:-${GITHUB_REPOSITORY:-noobping/infrastructure}}"
    export GH_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
    release_dir="$repo/dist/online/iso"
    assets=()
    release_error="$(mktemp)"
    trap 'rm -f -- "$release_error"' EXIT

    if [[ "${PUBLISH:-false}" != true ]]; then
        echo "set PUBLISH=true to update the $release_repo release" >&2
        exit 2
    fi

    run_podman() {
        if command -v podman >/dev/null 2>&1; then
            podman "$@"
        elif command -v flatpak-spawn >/dev/null 2>&1; then
            flatpak-spawn --host podman "$@"
        else
            echo "podman is required when the GitHub CLI is not installed" >&2
            exit 1
        fi
    }

    run_gh() {
        if command -v gh >/dev/null 2>&1; then
            gh "$@"
        elif command -v flatpak-spawn >/dev/null 2>&1 \
            && flatpak-spawn --host sh -lc 'command -v gh >/dev/null 2>&1'; then
            flatpak-spawn --host env GH_TOKEN="$GH_TOKEN" gh "$@"
        else
            if [[ -z "$GH_TOKEN" ]]; then
                echo "GH_TOKEN or GITHUB_TOKEN is required for containerized gh" >&2
                exit 1
            fi
            run_podman run --rm \
                -e GH_TOKEN \
                -v "$repo:$repo:Z" -w "$repo" \
                ghcr.io/cli/cli:latest "$@"
        fi
    }

    cd "$repo"
    command -v flock >/dev/null 2>&1 || {
        echo "flock is required to coordinate releases" >&2
        exit 1
    }
    exec 9>"$repo/dist/online/.release.lock"
    if ! flock -n 9; then
        echo "another release is already running in $repo" >&2
        exit 1
    fi

    for coreos_arch in x86_64 aarch64; do
        for profile in nas workstation sway; do
            for suffix in .iso .iso.sha256; do
                asset="$release_dir/${profile}-${coreos_arch}${suffix}"
                if [[ ! -s "$asset" ]]; then
                    echo "missing release asset: $asset" >&2
                    exit 1
                fi
                assets+=("$asset")
            done
        done
    done

    (
        cd "$release_dir"
        for coreos_arch in x86_64 aarch64; do
            for profile in nas workstation sway; do
                sha256sum --check "${profile}-${coreos_arch}.iso.sha256"
            done
        done
    )

    if run_gh release view continuous \
        --repo "$release_repo" >/dev/null 2> "$release_error"; then
        run_gh release upload continuous "${assets[@]}" \
            --repo "$release_repo" --clobber
        run_gh release edit continuous \
            --repo "$release_repo" \
            --title Continuous \
            --notes 'This release is automatically updated.' \
            --draft=false \
            --prerelease=false \
            --latest
    elif grep -Eqi 'release not found|HTTP 404' "$release_error"; then
        run_gh release create continuous "${assets[@]}" \
            --repo "$release_repo" \
            --title Continuous \
            --notes 'This release is automatically updated.' \
            --latest
    else
        cat "$release_error" >&2
        exit 1
    fi

[private]
_gitlab_media_publish:
    #!/usr/bin/env bash
    set -euo pipefail

    repo={{ quote(justfile_directory()) }}
    architecture="${BUILD_ARCHITECTURE:?BUILD_ARCHITECTURE is required}"
    profile="${BUILD_PROFILE:?BUILD_PROFILE is required}"
    : "${CI_API_V4_URL:?CI_API_V4_URL is required}"
    : "${CI_JOB_TOKEN:?CI_JOB_TOKEN is required}"
    : "${CI_JOB_ID:?CI_JOB_ID is required}"
    : "${CI_PIPELINE_IID:?CI_PIPELINE_IID is required}"
    : "${CI_PROJECT_ID:?CI_PROJECT_ID is required}"

    if [[ "${PUBLISH:-false}" != true ]]; then
        echo "set PUBLISH=true to publish GitLab installer assets" >&2
        exit 2
    fi
    for command in curl jq; do
        command -v "$command" >/dev/null 2>&1 || {
            echo "$command is required to publish GitLab installer assets" >&2
            exit 1
        }
    done

    case "$architecture" in
        amd64) coreos_arch=x86_64 ;;
        arm64) coreos_arch=aarch64 ;;
        *)
            echo "unsupported media architecture: $architecture" >&2
            exit 2
            ;;
    esac
    case "$profile" in
        nas|workstation|sway) ;;
        *)
            echo "unsupported media profile: $profile" >&2
            exit 2
            ;;
    esac

    package_name="${GITLAB_PACKAGE_PREFIX:-infrastructure}-${CI_JOB_ID}"
    package_version="${GITLAB_PACKAGE_VERSION:-continuous-${CI_PIPELINE_IID}}"
    package_url="$CI_API_V4_URL/projects/$CI_PROJECT_ID/packages/generic/$package_name/$package_version"
    release_dir="$repo/dist/online/iso"
    stem="$profile-$coreos_arch"

    for asset in "$release_dir/$stem.iso" "$release_dir/$stem.iso.sha256"; do
        if [[ ! -s "$asset" ]]; then
            echo "missing GitLab package asset: $asset" >&2
            exit 1
        fi
    done
    (cd "$release_dir" && sha256sum --check "$stem.iso.sha256")

    for asset in "$release_dir/$stem.iso" "$release_dir/$stem.iso.sha256"; do
        asset_name="${asset##*/}"
        asset_url="$package_url/$asset_name"
        curl --fail-with-body --location \
            --header "JOB-TOKEN: $CI_JOB_TOKEN" \
            --upload-file "$asset" "$asset_url"
    done

    marker_dir="$repo/dist/gitlab-media"
    mkdir -p "$marker_dir"
    jq --null-input \
        --arg iso_name "$stem.iso" \
        --arg iso_url "$package_url/$stem.iso" \
        --arg checksum_name "$stem.iso.sha256" \
        --arg checksum_url "$package_url/$stem.iso.sha256" \
        '[
            {name: $iso_name, url: $iso_url, link_type: "other"},
            {name: $checksum_name, url: $checksum_url, link_type: "other"}
        ]' > "$marker_dir/$stem.json"

[private]
_gitlab_release:
    #!/usr/bin/env bash
    set -euo pipefail

    repo={{ quote(justfile_directory()) }}
    : "${CI_API_V4_URL:?CI_API_V4_URL is required}"
    : "${CI_JOB_TOKEN:?CI_JOB_TOKEN is required}"
    : "${CI_JOB_ID:?CI_JOB_ID is required}"
    : "${CI_PIPELINE_IID:?CI_PIPELINE_IID is required}"
    : "${CI_PROJECT_ID:?CI_PROJECT_ID is required}"

    if [[ "${PUBLISH:-false}" != true ]]; then
        echo "set PUBLISH=true to publish the GitLab release" >&2
        exit 2
    fi
    command -v jq >/dev/null 2>&1 || {
        echo "jq is required to publish the GitLab release" >&2
        exit 1
    }

    release_tag="${GITLAB_RELEASE_TAG:-continuous-${CI_PIPELINE_IID}-${CI_JOB_ID}}"
    release_name="${GITLAB_RELEASE_NAME:-Continuous ${CI_PIPELINE_IID}}"
    release_repo="${GITLAB_RELEASE_REPOSITORY:-${CI_PROJECT_PATH:-}}"
    export GLAB_ENABLE_CI_AUTOLOGIN="${GLAB_ENABLE_CI_AUTOLOGIN:-true}"

    run_podman() {
        if command -v podman >/dev/null 2>&1; then
            podman "$@"
        elif command -v flatpak-spawn >/dev/null 2>&1; then
            flatpak-spawn --host podman "$@"
        else
            echo "podman is required when the GitLab CLI is not installed" >&2
            exit 1
        fi
    }

    run_glab() {
        if command -v glab >/dev/null 2>&1; then
            glab "$@"
        elif command -v flatpak-spawn >/dev/null 2>&1 \
            && flatpak-spawn --host sh -lc 'command -v glab >/dev/null 2>&1'; then
            flatpak-spawn --host env \
                CI_JOB_TOKEN="$CI_JOB_TOKEN" \
                GLAB_ENABLE_CI_AUTOLOGIN="$GLAB_ENABLE_CI_AUTOLOGIN" \
                glab "$@"
        else
            run_podman run --rm \
                -e CI_API_V4_URL \
                -e CI_JOB_TOKEN \
                -e CI_PROJECT_PATH \
                -e CI_PROJECT_URL \
                -e CI_SERVER_FQDN \
                -e CI_SERVER_HOST \
                -e CI_SERVER_PROTOCOL \
                -e GITLAB_CI \
                -e GLAB_ENABLE_CI_AUTOLOGIN \
                -v "$repo:$repo:Z" -w "$repo" \
                registry.gitlab.com/gitlab-org/cli:latest "$@"
        fi
    }

    glab_repo=()
    if [[ -n "$release_repo" ]]; then
        glab_repo=(--repo "$release_repo")
    fi

    marker_dir="$repo/dist/gitlab-media"
    shopt -s nullglob
    markers=("$marker_dir"/*.json)
    shopt -u nullglob
    if (( ${#markers[@]} != 6 )); then
        echo "expected six GitLab media markers in $marker_dir, found ${#markers[@]}" >&2
        exit 1
    fi
    for marker in "${markers[@]}"; do
        jq --exit-status '
            type == "array" and length == 2 and
            all(.[];
                (.name | type == "string") and
                (.url | type == "string") and
                .link_type == "other")
        ' "$marker" >/dev/null
    done
    asset_links="$(jq --slurp --compact-output 'add' "${markers[@]}")"

    for coreos_arch in x86_64 aarch64; do
        for profile in nas workstation sway; do
            for suffix in .iso .iso.sha256; do
                asset_name="$profile-$coreos_arch$suffix"
                count="$(jq --arg name "$asset_name" \
                    '[.[] | select(.name == $name)] | length' <<<"$asset_links")"
                if [[ "$count" != 1 ]]; then
                    echo "expected one GitLab media link named $asset_name, found $count" >&2
                    exit 1
                fi
            done
        done
    done

    package_prefix="$CI_API_V4_URL/projects/$CI_PROJECT_ID/packages/generic/"
    while IFS=$'\t' read -r asset_name asset_url; do
        if [[ "$asset_url" != "$package_prefix"*"/$asset_name" ]]; then
            echo "unexpected GitLab package URL for $asset_name: $asset_url" >&2
            exit 1
        fi
    done < <(jq -r '.[] | [.name, .url] | @tsv' <<<"$asset_links")

    if [[ -n "${CI_DEFAULT_BRANCH:-}" && -n "${CI_COMMIT_SHA:-}" ]]; then
        encoded_branch="$(jq -rn --arg value "$CI_DEFAULT_BRANCH" '$value | @uri')"
        branch_sha="$(curl --fail-with-body --silent --show-error --location \
            --header "JOB-TOKEN: $CI_JOB_TOKEN" \
            "$CI_API_V4_URL/projects/$CI_PROJECT_ID/repository/commits/$encoded_branch" |
            jq -r '.id')"
        if [[ "$branch_sha" != "$CI_COMMIT_SHA" ]]; then
            echo "Skipping stale release for $CI_COMMIT_SHA; $CI_DEFAULT_BRANCH is at $branch_sha."
            exit 0
        fi
    fi

    run_glab release create "$release_tag" \
        --assets-links "$asset_links" \
        --name "$release_name" \
        --notes "Build from ${CI_COMMIT_SHA:-HEAD}." \
        --ref "${CI_COMMIT_SHA:-HEAD}" \
        "${glab_repo[@]}"
