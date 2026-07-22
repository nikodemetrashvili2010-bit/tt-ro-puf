ARG VARIANT=ubuntu-24.04
FROM mcr.microsoft.com/vscode/devcontainers/base:${VARIANT}

ENV DEBIAN_FRONTEND=noninteractive
ENV PDK_ROOT=/home/vscode/ttsetup/pdk
ENV PDK=sky130A

RUN apt update
RUN apt install -y iverilog gtkwave ngspice python3 python3-pip python3-venv python3-tk python-is-python3 libcairo2 verilator libpng-dev libqhull-dev

# Pin the support scripts used by this image. Update this SHA intentionally.
ARG TT_SUPPORT_TOOLS_REF=d65690eeb1d4afd26aef795c805a23d9d9daf9d1
RUN mkdir -p /ttsetup
RUN git clone --no-checkout https://github.com/TinyTapeout/tt-support-tools /ttsetup/tt-support-tools && \
    git -C /ttsetup/tt-support-tools checkout --detach ${TT_SUPPORT_TOOLS_REF} && \
    test "$(git -C /ttsetup/tt-support-tools rev-parse HEAD)" = "${TT_SUPPORT_TOOLS_REF}"

COPY test/requirements.txt /ttsetup/test_requirements.txt
COPY requirements-analysis.txt /ttsetup/analysis_requirements.txt
COPY .devcontainer/copy_tt_support_tools.sh /ttsetup

RUN python -m venv /ttsetup/venv
RUN /ttsetup/venv/bin/pip install -r /ttsetup/test_requirements.txt -r /ttsetup/analysis_requirements.txt -r /ttsetup/tt-support-tools/requirements.txt
RUN chmod 755 /ttsetup/copy_tt_support_tools.sh

# Install the pinned Verible release and verify GitHub's published asset digest.
ARG VERIBLE_SHA256=30c20385956f52ef892cb58f7f816f9f9a9dc37a0432848a49c6d9aa3a72a8b7
RUN umask 022 && \
    curl --fail --location --output /tmp/verible.tar.gz \
      https://github.com/chipsalliance/verible/releases/download/v0.0-4023-gc1271a00/verible-v0.0-4023-gc1271a00-linux-static-x86_64.tar.gz && \
    echo "${VERIBLE_SHA256}  /tmp/verible.tar.gz" | sha256sum --check --strict && \
    tar zxf /tmp/verible.tar.gz -C /usr/local --strip-components=1 && \
    rm /tmp/verible.tar.gz && \
    chmod 755 /usr/local/bin

# Install LibreLane
RUN /ttsetup/venv/bin/pip install librelane==2.4.2
