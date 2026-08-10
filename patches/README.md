# Patches Directory

Patches are organized by package type and ABI/runtime target.

A patch file is not a binary package. A target becomes release-supported only
after it has a package workflow, artifact upload, release workflow integration,
and a runtime smoke test. The current target verification checklist lives in
[`docs/build-packaging/packaging.md`](../docs/build-packaging/packaging.md) and
[`packaging/compatibility-map.yml`](../packaging/compatibility-map.yml).

## Patch Tree

```text
patches/
|-- common/
|   |-- add-drive-linux-drawer-rail.patch
|   `-- fix-tauri-worker-protocol.patch
`-- deb/
    |-- debian.12.patch
    |-- debian.13.patch
    |-- ubuntu.24.04.patch
    `-- ubuntu.26.04.patch
```

## Release-Gated Patches

These are currently built and published by the release workflow:

- `deb/debian.12.patch`
- `deb/debian.13.patch`
- `deb/ubuntu.24.04.patch`
- `deb/ubuntu.26.04.patch`

`common/` patches are applied during every package build and are not
target-specific.

## Patch Rules

1. Base code is universal. `src-tauri/src/main.rs` must not hard-code distro
   WebKitGTK environment values.
2. Distro-specific overrides go in `patches/deb/<target>.patch`.
3. `patches/common/` is only for changes every package needs.
4. One target owns one patch file. Do not split target behavior across multiple
   patch files.

## Adding a Target

1. Create the patch against the clean repository base.
2. Name it after the ABI target, for example `ubuntu.24.04.patch`.
3. Test repository patches with `git apply --check`.
4. For `common/` patches that apply to cloned WebClients, test after
   `scripts/build-webclients.sh` has cloned WebClients.
5. Add the target to `packaging/compatibility-map.yml`.
6. Add or update documentation in `docs/build-packaging/packaging.md`.
7. Promote to release-gated only after a workflow, artifact upload, release
   integration, and runtime smoke test exist.
