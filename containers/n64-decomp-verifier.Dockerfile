FROM ubuntu:24.04

ARG TARGETARCH
ARG IDO_COMMIT=d5aec59932034b8a20f23f471297a55c45dcbc45
ARG OBJDIFF_VERSION=3.7.3

ENV DEBIAN_FRONTEND=noninteractive
ENV PATH="/root/.local/bin:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
    binutils-mips-linux-gnu \
    build-essential \
    ca-certificates \
    curl \
    git \
    make \
    python3 \
    python3-pip \
    ripgrep \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

RUN git clone https://github.com/decompals/ido-static-recomp.git \
      /opt/ido-static-recomp \
    && git -C /opt/ido-static-recomp checkout "${IDO_COMMIT}" \
    && make -C /opt/ido-static-recomp -j"$(nproc)" RELEASE=1 setup \
    && make -C /opt/ido-static-recomp -j"$(nproc)" RELEASE=1 VERSION=7.1 \
    && make -C /opt/ido-static-recomp -j"$(nproc)" RELEASE=1 VERSION=5.3 \
    && rm -rf /opt/ido-static-recomp/.git

RUN case "${TARGETARCH}" in \
      amd64) objdiff_arch=x86_64 ;; \
      arm64) objdiff_arch=aarch64 ;; \
      *) echo "unsupported TARGETARCH=${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && curl -fL \
      "https://github.com/encounter/objdiff/releases/download/v${OBJDIFF_VERSION}/objdiff-cli-linux-${objdiff_arch}" \
      -o /usr/local/bin/objdiff-cli \
    && chmod 0755 /usr/local/bin/objdiff-cli

# Early 1080 revisions resolve asm-processor through ../../tools. Preserve the
# project's pinned vendored copy at a stable image path for historical replay.
COPY projects/1080-decomp/tools/asm-processor /opt/asm-processor

COPY pyproject.toml README.md /opt/decomp/
COPY decomp /opt/decomp/decomp
RUN uv pip install --system /opt/decomp

WORKDIR /workspace
