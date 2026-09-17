mod online

check-whitespace:
    #!/usr/bin/env bash
    set -euo pipefail
    git diff --check
    git diff --cached --check
    git log -1 --check --format=

check-just:
    #!/usr/bin/env bash
    set -euo pipefail
    just={{ quote(just_executable()) }}
    "$just" --fmt --check
    script="$(mktemp)"
    trap 'rm -f -- "$script"' EXIT
    commands=(
        "online::_images stable both all"
        "online::_images stable amd64 nas"
        "online::_images stable arm64 policy"
        "online::_images stable preflight all"
        "online::_images stable manifests jellyfin"
        "online::_images next both all"
        "online::_images next arm64 workstation"
        "online::_images next amd64 policy"
        "online::_images next manifests sway"
        "online::_media both all"
        "online::_media amd64 nas"
        "online::_release"
        "online::_gitlab_media_publish"
        "online::_gitlab_release"
        "online::image-task"
        "online::gitlab-media-publish"
        "online::gitlab-manifest-task"
        "online::gitlab-release-assets"
        "online::manifest-preflight"
        "online::manifest-task"
        "online::media-task"
        "_offline all both"
        "_offline workstation both"
        "_offline nas both"
        "_offline sway both"
    )
    for command in "${commands[@]}"; do
        read -r -a arguments <<< "$command"
        "$just" --dry-run "${arguments[@]}" >/dev/null 2> "$script"
        bash -n "$script"
    done

check-shell:
    #!/usr/bin/env bash
    set -euo pipefail
    failed=0
    while IFS= read -r -d '' file; do
        [[ -f "$file" ]] || continue
        first_line=
        IFS= read -r first_line < "$file" || true
        if [[ "$first_line" == '#!'*bash* || "$first_line" == '#!'*'/sh'* ]]; then
            if ! bash -n "$file"; then
                failed=1
            fi
        fi
    done < <(git ls-files -z)
    exit "$failed"

check-workstation:
    bash images/workstation/test/chatgpt-install

offline selection="all" architecture="native": (_offline selection architecture)

# Build every offline image and installer for both supported architectures.
offline-build:
    @{{ quote(just_executable()) }} _offline all both

# Build the offline Workstation image and installers for both architectures.
offline-workstation-build:
    @{{ quote(just_executable()) }} _offline workstation both

# Build the offline NAS image and installers for both architectures.
offline-nas-build:
    @{{ quote(just_executable()) }} _offline nas both

# Build the offline Sway image and installers for both architectures.
offline-sway-build:
    @{{ quote(just_executable()) }} _offline sway both

[private]
_offline target architecture:
    #!/usr/bin/env bash
    set -euo pipefail

    repo={{ quote(justfile_directory()) }}
    target={{ quote(target) }}
    architecture={{ quote(architecture) }}
    namespace="${IMAGE_NAMESPACE:-localhost:5000/noobping}"
    tls_verify="${REGISTRY_TLS_VERIFY:-false}"
    isolation="${BUILDAH_ISOLATION:-chroot}"
    tmpdir="${TMPDIR:-/tmp}"
    source_url="$(git -C "$repo" config --get remote.origin.url || printf '%s' "$repo")"
    revision="$(git -C "$repo" rev-parse HEAD)"

    case "$target" in
        all|workstation|nas|sway) ;;
        native|both|amd64|x86_64|arm64|aarch64)
            if [[ "$architecture" != native ]]; then
                echo "architecture specified twice: $target $architecture" >&2
                exit 2
            fi
            architecture="$target"
            target=all
            ;;
        *)
            echo "unsupported offline target: $target" >&2
            exit 2
            ;;
    esac

    case "$(uname -m)" in
        x86_64)
            native_arch=amd64
            ;;
        aarch64|arm64)
            native_arch=arm64
            ;;
        *)
            echo "offline does not support $(uname -m)" >&2
            exit 1
            ;;
    esac

    case "$architecture" in
        native)
            build_arches=("$native_arch")
            ;;
        both)
            if [[ "$native_arch" == amd64 ]]; then
                build_arches=(amd64 arm64)
            else
                build_arches=(arm64 amd64)
            fi
            ;;
        amd64|x86_64)
            build_arches=(amd64)
            ;;
        arm64|aarch64)
            build_arches=(arm64)
            ;;
        *)
            echo "unsupported architecture: $architecture" >&2
            echo "expected native, amd64, arm64, or both" >&2
            exit 2
            ;;
    esac

    registry="${namespace%%/*}"
    case "$registry" in
        localhost:*|127.0.0.1:*) ;;
        *)
            echo "offline requires a local IMAGE_NAMESPACE; got $namespace" >&2
            exit 1
            ;;
    esac

    registry_host="${registry%:*}"
    registry_port="${registry##*:}"
    registry_container="${LOCAL_REGISTRY_CONTAINER:-pipeline-registry}"
    registry_volume="${LOCAL_REGISTRY_VOLUME:-pipeline-registry}"

    run_podman() {
        if command -v podman >/dev/null 2>&1; then
            podman "$@"
        elif command -v flatpak-spawn >/dev/null 2>&1; then
            flatpak-spawn --host podman "$@"
        else
            echo "podman is required to build offline artifacts" >&2
            exit 1
        fi
    }

    run_buildah() {
        if command -v buildah >/dev/null 2>&1; then
            TMPDIR="$tmpdir" buildah "$@"
        elif command -v flatpak-spawn >/dev/null 2>&1; then
            flatpak-spawn --host env TMPDIR="$tmpdir" buildah "$@"
        else
            echo "buildah is required to build offline artifacts" >&2
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
                -v "$repo:/work:Z" -w /work \
                docker.io/mikefarah/yq:4.45.1 "$@"
        fi
    }

    set_arch() {
        image_arch="$1"
        case "$image_arch" in
            amd64)
                coreos_arch=x86_64
                expected_machine=x86_64
                ;;
            arm64)
                coreos_arch=aarch64
                expected_machine=aarch64
                ;;
        esac
    }

    check_arch_runtime() {
        local requested_arch="$1"
        local actual

        if [[ "$requested_arch" == "$native_arch" ]]; then
            return 0
        fi

        set_arch "$requested_arch"
        printf 'Checking %s container emulation...\n' "$requested_arch"
        if ! actual="$(run_podman run --rm --pull=missing \
            --arch "$requested_arch" \
            quay.io/fedora/fedora-minimal:latest uname -m)"; then
            echo "cannot execute $requested_arch containers" >&2
            echo "enable QEMU/binfmt on the host or build on a native machine" >&2
            exit 1
        fi
        if [[ "$actual" != "$expected_machine" ]]; then
            echo "expected $expected_machine emulation, got $actual" >&2
            exit 1
        fi
    }

    write_iso_with_archive() {
        local input_host="$1"
        local output_host="$2"
        local archive_host="$3"
        local input_container="$4"
        local output_container="$5"
        local archive_container="$6"

        if command -v xorriso >/dev/null 2>&1; then
            xorriso \
                -indev "$input_host" \
                -outdev "$output_host" \
                -boot_image any replay \
                -map "$archive_host" /bootc
        elif command -v flatpak-spawn >/dev/null 2>&1 \
            && flatpak-spawn --host sh -lc 'command -v xorriso >/dev/null 2>&1'; then
            flatpak-spawn --host xorriso \
                -indev "$input_host" \
                -outdev "$output_host" \
                -boot_image any replay \
                -map "$archive_host" /bootc
        else
            run_podman run --rm \
                -v "$repo:/work:Z" -w /work \
                -v "$work_dir:/work-tmp:Z" \
                registry.fedoraproject.org/fedora:latest \
                sh -lc 'dnf -y -q install xorriso >/dev/null; exec xorriso "$@"' \
                sh \
                -indev "$input_container" \
                -outdev "$output_container" \
                -boot_image any replay \
                -map "$archive_container" /bootc
        fi
    }

    registry_ready() {
        if command -v curl >/dev/null 2>&1; then
            curl -fsS "http://${registry}/v2/" >/dev/null 2>&1
            return $?
        fi
        if command -v wget >/dev/null 2>&1; then
            wget -q -O /dev/null "http://${registry}/v2/" >/dev/null 2>&1
            return $?
        fi
        (echo >/dev/tcp/"$registry_host"/"$registry_port") >/dev/null 2>&1
    }

    ensure_registry() {
        if registry_ready; then
            printf 'Local registry already running at %s\n' "$registry"
            return 0
        fi

        if run_podman container exists "$registry_container"; then
            run_podman start "$registry_container" >/dev/null
        else
            run_podman volume exists "$registry_volume" >/dev/null 2>&1 \
                || run_podman volume create "$registry_volume" >/dev/null
            run_podman run -d \
                --name "$registry_container" \
                -p "127.0.0.1:${registry_port}:5000" \
                -v "${registry_volume}:/var/lib/registry:Z" \
                docker.io/library/registry:2 >/dev/null
        fi

        for _ in {1..30}; do
            if registry_ready; then
                printf 'Local registry running at %s\n' "$registry"
                return 0
            fi
            sleep 1
        done

        echo "local registry did not become ready at $registry" >&2
        run_podman logs "$registry_container" >&2 || true
        exit 1
    }

    render_butane() {
        local input="$1"
        local output="$2"
        local bootc_image="$3"

        sed \
            -e "s#__IMAGE_NAMESPACE__#${namespace}#g" \
            -e "s#__BOOTC_IMAGE__#${bootc_image}#g" \
            "$input" > "$output"
    }

    build_image() {
        local context="$1"
        local name="$2"
        local arch_image="${namespace}/${name}:${image_arch}"
        shift 2

        printf '\n==> Building %s\n' "$arch_image"
        run_buildah bud \
            --layers \
            --pull=always \
            --arch "$image_arch" \
            --isolation="$isolation" \
            -t "$arch_image" \
            --label "org.opencontainers.image.source=${source_url}" \
            "$@" \
            "$context"

        run_buildah push --tls-verify="$tls_verify" \
            "$arch_image" "docker://$arch_image"
    }

    remove_local_ref() {
        local image="$1"

        run_buildah manifest rm "$image" >/dev/null 2>&1 || true
        run_buildah rmi "$image" >/dev/null 2>&1 || true
    }

    publish_single_latest() {
        local architecture="$1"
        local name arch_image latest_image
        shift

        for name in "$@"; do
            arch_image="${namespace}/${name}:${architecture}"
            latest_image="${namespace}/${name}:latest"
            printf '\n==> Publishing %s from %s\n' "$latest_image" "$arch_image"
            remove_local_ref "$latest_image"
            run_buildah tag "$arch_image" "$latest_image"
            run_buildah push --tls-verify="$tls_verify" \
                "$latest_image" "docker://$latest_image"
        done
    }

    publish_multiarch_latest() {
        local name architecture latest_image manifest_image

        for name in "$@"; do
            latest_image="${namespace}/${name}:latest"
            manifest_image="localhost/pipeline-offline-${name}:${BASHPID}"
            printf '\n==> Publishing multi-architecture %s\n' "$latest_image"
            remove_local_ref "$latest_image"
            remove_local_ref "$manifest_image"
            run_buildah manifest create "$manifest_image"
            for architecture in amd64 arm64; do
                run_buildah manifest add "$manifest_image" \
                    "${namespace}/${name}:${architecture}"
            done
            run_buildah manifest push --all --tls-verify="$tls_verify" \
                "$manifest_image" "docker://$latest_image"
            run_buildah manifest rm "$manifest_image" >/dev/null
        done
    }

    build_ips() {
        build_image images/ips ips --build-arg FCOS_STREAM=stable
    }

    build_policy() {
        build_image images/policy policy \
            --build-arg "POLICY_VERSION=${revision}"
    }

    build_workstation() {
        build_image images/workstation workstation \
            --tls-verify="$tls_verify" \
            --build-arg "IMAGE_NAMESPACE=${namespace}" \
            --build-arg "POLICY_IMAGE=${namespace}/policy:${image_arch}" \
            --build-arg "TAG=${image_arch}"
    }

    build_nas() {
        build_image images/nas nas \
            --tls-verify="$tls_verify" \
            --build-arg "IMAGE_NAMESPACE=${namespace}" \
            --build-arg "POLICY_IMAGE=${namespace}/policy:${image_arch}" \
            --build-arg "TAG=${image_arch}"
    }

    build_vm() {
        build_image vms/vm vm \
            --tls-verify="$tls_verify" \
            --build-arg "IMAGE_NAMESPACE=${namespace}" \
            --build-arg "TAG=${image_arch}"
    }

    build_sway() {
        build_image images/sway sway \
            --tls-verify="$tls_verify" \
            --build-arg "IMAGE_NAMESPACE=${namespace}" \
            --build-arg "TAG=${image_arch}"
    }

    build_k3s() {
        build_image vms/k3s k3s \
            --tls-verify="$tls_verify" \
            --build-arg "IMAGE_NAMESPACE=${namespace}" \
            --build-arg "TAG=${image_arch}"
    }

    build_minecraft() {
        build_image vms/minecraft minecraft \
            --tls-verify="$tls_verify" \
            --build-arg "IMAGE_NAMESPACE=${namespace}" \
            --build-arg "TAG=${image_arch}"
    }

    build_jellyfin() {
        build_image vms/jellyfin jellyfin \
            --tls-verify="$tls_verify" \
            --build-arg "IMAGE_NAMESPACE=${namespace}" \
            --build-arg "TAG=${image_arch}"
    }

    build_workstation_branch() {
        build_workstation
        build_sway
    }

    build_vm_branch() {
        build_vm
        run_parallel build_k3s build_minecraft build_jellyfin
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
                printf 'offline task failed: %s\n' "${tasks[$index]}" >&2
                failed=1
            fi
        done

        (( failed == 0 ))
    }

    build_ignition() {
        local input="$1"
        local output="$2"

        run_podman run --rm \
            -v "$repo:/work:Z" -w /work \
            quay.io/coreos/butane:release \
            --pretty --strict --files-dir . "$input" \
            > "$output"

        run_podman run --rm -i \
            quay.io/coreos/ignition-validate:release \
            - < "$output"
    }

    render_profile() {
        local profile="$1"
        local source_profile="$2"

        run_yq ea '. as $item ireduce ({}; . *+ $item)' \
            butane/base.yml \
            butane/updates.yml \
            "butane/${source_profile}.yml" \
            > "dist/butane/${profile}.bu"
        render_butane \
            "dist/butane/${profile}.bu" \
            "dist/butane/${profile}.rendered.bu" \
            "$profile"
        build_ignition \
            "dist/butane/${profile}.rendered.bu" \
            "dist/ign/${profile}.ign"
    }

    render_guest() {
        local guest="$1"

        run_yq ea '. as $item ireduce ({}; . *+ $item)' \
            butane/base.yml \
            butane/updates.yml \
            butane/vm.yml \
            "butane/${guest}.yml" \
            > "dist/butane/${guest}.bu"
        render_butane \
            "dist/butane/${guest}.bu" \
            "dist/butane/${guest}.rendered.bu" \
            "$guest"
        build_ignition \
            "dist/butane/${guest}.rendered.bu" \
            "dist/ign/${guest}.ign"
    }

    build_installer() {
        local profile="$1"
        local profile_dir="$work_dir/$profile"
        local archive_dir="$profile_dir/bootc"
        local archive_dir_container="/work-tmp/${profile}/bootc"
        local archive="$archive_dir/${profile}.ociarchive"
        local custom_iso="$profile_dir/custom.iso"
        local custom_iso_container="/work-tmp/${profile}/custom.iso"
        local out_iso="dist/iso/${profile}-offline-${coreos_arch}.iso"
        local out_iso_container="/work/${out_iso}"

        printf '\n==> Building %s\n' "$out_iso"
        mkdir -p "$archive_dir"
        rm -f "$out_iso" "${out_iso}.sha256"

        run_podman pull --tls-verify="$tls_verify" \
            --arch "$image_arch" \
            "${namespace}/${profile}:${image_arch}"
        run_podman save --format oci-archive -o "$archive" \
            "${namespace}/${profile}:${image_arch}"
        (
            cd "$archive_dir"
            sha256sum "${profile}.ociarchive" \
                > "${profile}.ociarchive.sha256"
        )

        run_podman run --rm \
            --userns=keep-id \
            --user "$(id -u):$(id -g)" \
            -v "$repo:/work:Z" -w /work \
            -v "$work_dir:/work-tmp:Z" \
            quay.io/coreos/coreos-installer:release \
            iso customize \
                --live-ignition dist/ign/setup.ign \
                --dest-ignition "dist/ign/${profile}.ign" \
                --pre-install butane/bin/detect-device \
                -o "$custom_iso_container" \
                "$base_iso"

        write_iso_with_archive \
            "$custom_iso" \
            "$out_iso" \
            "$archive_dir" \
            "$custom_iso_container" \
            "$out_iso_container" \
            "$archive_dir_container"

        (
            cd dist/iso
            sha256sum "${profile}-offline-${coreos_arch}.iso" \
                > "${profile}-offline-${coreos_arch}.iso.sha256"
        )
        rm -rf -- "$profile_dir"
    }

    cd "$repo"
    mkdir -p dist/butane dist/ign dist/iso

    case "$target" in
        all)
            profiles=(nas workstation sway)
            image_names=(ips policy workstation sway nas vm k3s minecraft jellyfin)
            ;;
        workstation)
            profiles=(workstation)
            image_names=(ips policy workstation)
            ;;
        nas)
            profiles=(nas)
            image_names=(ips policy nas)
            ;;
        sway)
            profiles=(sway)
            image_names=(ips policy workstation sway)
            ;;
    esac

    if ! command -v flock >/dev/null 2>&1; then
        echo "flock is required to coordinate offline builds" >&2
        exit 1
    fi
    exec 9>dist/.offline.lock
    if ! flock -n 9; then
        echo "another offline build is already running in $repo" >&2
        exit 1
    fi

    for requested_arch in "${build_arches[@]}"; do
        check_arch_runtime "$requested_arch"
    done

    ensure_registry

    # Keep the staging directory under the checkout so host-side Podman can see
    # it even when Just is running inside a Flatpak sandbox with a private /tmp.
    work_dir="$(mktemp -d "$repo/dist/.pipeline-offline.XXXXXX")"
    trap 'rm -rf -- "$work_dir"' EXIT

    run_yq ea '. as $item ireduce ({}; . *+ $item)' \
        butane/base.yml \
        butane/setup.yml \
        > dist/butane/setup.bu
    render_butane \
        dist/butane/setup.bu \
        dist/butane/setup.rendered.bu \
        workstation
    build_ignition dist/butane/setup.rendered.bu dist/ign/setup.ign

    if [[ "$target" == all || "${BUILD_ALL_IGNITION:-false}" == true ]]; then
        render_profile nas nas
        render_profile workstation workstation
        render_profile sway workstation
        for guest in k3s minecraft jellyfin; do
            render_guest "$guest"
        done
    else
        for profile in "${profiles[@]}"; do
            if [[ "$profile" == sway ]]; then
                render_profile sway workstation
            else
                render_profile "$profile" "$profile"
            fi
        done
    fi

    for requested_arch in "${build_arches[@]}"; do
        set_arch "$requested_arch"
        printf '\n========== Building %s (%s) ==========\n' \
            "$image_arch" "$coreos_arch"

        run_parallel build_ips build_policy

        case "$target" in
            all) run_parallel build_workstation_branch build_nas build_vm_branch ;;
            workstation) build_workstation ;;
            nas) build_nas ;;
            sway) build_workstation_branch ;;
        esac

        if ! ls -1 fedora-coreos-*-live-iso."${coreos_arch}".iso >/dev/null 2>&1; then
            run_podman run --rm \
                --userns=keep-id \
                --user "$(id -u):$(id -g)" \
                -v "$repo:/work:Z" -w /work \
                quay.io/coreos/coreos-installer:release \
                download -s stable -a "$coreos_arch" -p metal -f iso -C /work --decompress
        fi

        base_iso="$(ls -1t fedora-coreos-*-live-iso."${coreos_arch}".iso | sed -n '1p')"
        for profile in "${profiles[@]}"; do
            build_installer "$profile"
        done
    done

    if (( ${#build_arches[@]} == 2 )); then
        publish_multiarch_latest "${image_names[@]}"
    else
        publish_single_latest "${build_arches[0]}" "${image_names[@]}"
    fi

    printf '\nBuilt %s images for %s in %s and installer artifacts in %s/dist.\n' \
        "$target" "${build_arches[*]}" "$namespace" "$repo"
