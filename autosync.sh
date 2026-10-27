#!/usr/bin/env bash
# The scheduled sync in the Docker setup (docker compose run --rm sync): the
# same `wellbeing autosync` the no-Docker Windows setup runs. It reads the
# phone's new uploads, logs to data/autosync.log, and does nothing when the
# phone hasn't uploaded yet or another sync is running.
cd "$(dirname "$0")" && exec "${PY:-python}" -m wellbeing autosync
