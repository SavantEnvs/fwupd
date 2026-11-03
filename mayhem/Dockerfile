# syntax=docker/dockerfile:1.7
#
# Commit image for fwupd: the whole repo (incl. .git) lives in /mayhem, built by mayhem/build.sh.
#   docker build -f mayhem/Dockerfile --build-arg COMMIT=$(git rev-parse HEAD) -t fwupd-commit:test .
FROM ghcr.io/savantenvs/base:20261023

ARG COMMIT
ARG REPO_URL
ARG SOURCE_DATE_EPOCH
ARG SANITIZER_FLAGS
ARG COVERAGE_FLAGS=
ARG MAYHEM_JOBS=

ARG RUST_CHANNEL=1.88.0

# System libraries the fuzz harnesses link against (glib/gio, libxmlb, libusb, compression) plus
# python3-jinja2 for libfwupdplugin/rustgen.py. Installed as root before the build so that
# build.sh itself never needs the network.
USER root
RUN if [ -n "$SOURCE_DATE_EPOCH" ]; then repro-sources-list.sh || true; fi; \
    apt-get update && apt-get install -yq --no-install-recommends \
        libglib2.0-dev libxmlb-dev libusb-1.0-0-dev liblzma-dev libzstd-dev zlib1g-dev \
        libffi-dev python3-jinja2 zip \
 && rm -rf /var/lib/apt/lists/*

# Rust toolchain for rust/fwupd-ffi (a staticlib linked into every harness), pinned under
# /opt/toolchains/rust with a $HOME-independent CARGO_HOME. The workspace has no third-party
# crates, so the air-gapped re-run needs nothing from the network.
ENV RUSTUP_HOME=/opt/toolchains/rust/rustup \
    CARGO_HOME=/opt/toolchains/rust/cargo \
    PATH=/opt/toolchains/rust/cargo/bin:${PATH}
RUN install -d /opt/toolchains/rust \
 && curl --proto '=https' --tlsv1.2 -fsSL https://sh.rustup.rs -o /tmp/rustup-init.sh \
 && sh /tmp/rustup-init.sh -y --no-modify-path --profile minimal --default-toolchain "${RUST_CHANNEL}" \
 && rm -f /tmp/rustup-init.sh \
 && chown -R 2000:2000 /opt/toolchains/rust

USER mayhem
WORKDIR /mayhem
COPY --chown=2000:2000 . /mayhem

RUN if [ -x /opt/mayhem/ccache/prefill ]; then /opt/mayhem/ccache/prefill bash mayhem/build.sh; \
    else bash mayhem/build.sh; fi

RUN if [ -f mayhem/test.sh ]; then bash mayhem/test.sh; else echo "no mayhem/test.sh — repo ships no functional tests"; fi

LABEL org.opencontainers.image.source="${REPO_URL}" \
      org.opencontainers.image.revision="${COMMIT}" \
      rlenv.tier="commit" \
      rlenv.source_date_epoch="${SOURCE_DATE_EPOCH}" \
      rlenv.user="mayhem"

USER mayhem
WORKDIR /mayhem
