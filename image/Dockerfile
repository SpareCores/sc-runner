FROM python:3.12
VOLUME /data/workdir
VOLUME /data/backend
ENV PULUMI_CONFIG_PASSPHRASE=""
ENV VIRTUAL_ENV="/pulumi_venv"
ENV PATH=/root/.pulumi/bin:$VIRTUAL_ENV/bin:$PATH
RUN curl -fsSL https://get.pulumi.com | sh && for i in azure-native aws gcp; do pulumi plugin install resource $i; done
RUN --mount=id=root,type=cache,target=/root,sharing=shared \
    python -m venv --without-pip "$VIRTUAL_ENV" && \
    curl -sSLf https://bootstrap.pypa.io/get-pip.py | python - && \
    pip install "sparecores-runner>=0.0.35"
ENTRYPOINT sc-runner