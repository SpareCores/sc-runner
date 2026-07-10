FROM python:3.12
VOLUME /data/workdir
VOLUME /data/backend
ENV PULUMI_CONFIG_PASSPHRASE=""
ENV VIRTUAL_ENV="/pulumi_venv"
ENV PATH=/root/.pulumi/bin:$VIRTUAL_ENV/bin:$PATH
RUN curl -fsSL https://get.pulumi.com | sh && \
    for i in \
    azure-native aws gcp alicloud; \
    do pulumi plugin install resource $i; done
# RUNNER_VERSION pins an exact PyPI release (set by the tag-release workflow).
# Leave empty on main-branch builds to install the latest sparecores-runner.
ARG RUNNER_VERSION
RUN --mount=id=root,type=cache,target=/root,sharing=shared \
    python -m venv "$VIRTUAL_ENV" && \
    "$VIRTUAL_ENV/bin/pip" install uv && \
    if [ -n "$RUNNER_VERSION" ]; then \
      SPEC="sparecores-runner==${RUNNER_VERSION}"; \
    else \
      SPEC="sparecores-runner"; \
    fi && \
    uv pip install "$SPEC" --python "$VIRTUAL_ENV/bin/python"
ENTRYPOINT sc-runner
