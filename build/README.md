# Build and release

The build targets portal package `1.11.0~1792525517~24.04~f448ddf` on Pop!_OS 24.04 x86-64. It pins portal commit `f448ddfb296bf7bb23517b24b2f532559a334a1c` and capture-library fork commit `3ad1781fefeaea5224ec6917f53ccad32bf5219b`.

The original 1.10.0 executable remains available from release v1.0.0. The release generator embeds both verified downloads in the installer; it does not use a floating latest-release URL.

## GitHub Actions

The `Build capture fix` workflow builds on an Ubuntu 24.04 GitHub-hosted runner. It runs installer and restore tests, verifies the upstream package checksum, checks both capture ordering regressions before and after the fix, and confirms that unrelated locked dependencies did not change.

A successful build uploads the candidate files, creates branch `release/v1.1.0` containing the generated installer and README, and prepares a **draft** release. Existing public release files are retained. The workflow's summary links to the draft release and gives the exact desktop test command.

After a successful desktop capture test:

1. Publish the v1.1.0 draft release.
2. Merge `release/v1.1.0` into `main` to update the public installation command.

Publish before merging the README so the new download exists when users first see its command. Do not move or replace the published v1.0.0 tag or assets.

## Local reproduction

With Docker available, from the repository root:

```bash
docker build --file build/Containerfile --tag cosmic-capture-builder .
mkdir output
docker run --rm --cap-drop=ALL --security-opt=no-new-privileges \
  --user "$(id -u):$(id -g)" \
  --env HOME=/tmp/capture-build-home \
  --env CARGO_HOME=/tmp/capture-build-cargo \
  --env CARGO_BUILD_JOBS="$(nproc)" \
  --mount "type=bind,src=$PWD,dst=/input,readonly" \
  --mount "type=bind,src=$PWD/output,dst=/out" \
  cosmic-capture-builder python3 /input/build/build.py
python3 build/prepare-release.py --output output \
  --repository MagnetosphereLabs/pop-os-cosmic-capture-freeze-fix
```

The build produces files under `output`; it does not install the portal. Compilers, downloaded source trees, and dependency caches are inside the temporary container. To remove only the local build image after retaining the desired outputs, run `docker image rm cosmic-capture-builder`.
