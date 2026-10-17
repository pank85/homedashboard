#!/bin/bash
# FR5 process lifecycle. This script always reaches uvicorn.
# embedded (default): start herdr when the binary exists and a server is not already up.
# external and off: do not start herdr.
# Unknown HERDR_MODE: do not start herdr, so a typo cannot spawn a server.
# Settings may still treat an unknown mode as embedded for the href default only.
set -u

cd /app || echo "warning: could not cd /app; continuing" >&2

export PATH="/usr/local/bin:/root/.local/bin:/root/.bun/bin:${PATH:-}"

# Empty HERDR_CONFIG_DIR means unset. Export herdr's own override when the file is mounted.
if [ -n "${HERDR_CONFIG_DIR:-}" ] && [ -f "${HERDR_CONFIG_DIR}/config.toml" ]; then
  export HERDR_CONFIG_PATH="${HERDR_CONFIG_DIR}/config.toml"
fi

HERDR_MODE="${HERDR_MODE:-embedded}"
HERDR_WEB_BIND="${HERDR_WEB_BIND:-127.0.0.1}"
HERDR_WEB_PORT="${HERDR_WEB_PORT:-7317}"

# herdr status server exits 0 even when it prints "status: not running".
# Running only if a line matches "status: running" and not "not running".
# A socket path must not override a not-running line.
herdr_output_is_running() {
  local line
  while IFS= read -r line || [ -n "${line}" ]; do
    case "${line}" in
      *'not running'*)
        ;;
      *'status: running'*)
        return 0
        ;;
    esac
  done
  return 1
}

herdr_status() {
  local out rc
  if command -v timeout >/dev/null 2>&1; then
    out="$(timeout 3 herdr status server 2>&1)"
  else
    out="$(herdr status server 2>&1)"
  fi
  rc=$?
  if [ "${rc}" -ne 0 ]; then
    printf '%s\n' "herdr status server failed (${rc}): ${out}" >>/tmp/herdr-server.log 2>/dev/null || true
    echo "herdr status server failed (${rc}); see /tmp/herdr-server.log" >&2
    return "${rc}"
  fi
  if printf '%s\n' "${out}" | herdr_output_is_running; then
    return 0
  fi
  return 1
}

# Plugin reads HOST and PORT from `env` (no leading dot, mode 600) in its config dir,
# not from the ambient environment. Other keys are kept. Failure must not stop uvicorn.
write_web_ui_env() {
  local dir file tmp line key trimmed
  dir="$(herdr plugin config-dir devswha.herdr-web-ui 2>>/tmp/herdr-web.log)" || {
    echo "herdr plugin config-dir failed; web ui HOST/PORT not written" >&2
    return 0
  }
  dir="${dir%%$'\n'*}"
  dir="${dir//$'\r'/}"
  dir="${dir#"${dir%%[![:space:]]*}"}"
  dir="${dir%"${dir##*[![:space:]]}"}"
  if [ -z "${dir}" ]; then
    echo "herdr plugin config-dir returned empty; web ui HOST/PORT not written" >&2
    return 0
  fi
  if [ ! -d "${dir}" ]; then
    mkdir -p "${dir}" || {
      echo "could not create herdr web ui config dir; continuing" >&2
      return 0
    }
  fi
  file="${dir}/env"
  tmp="${file}.tmp.$$"
  : > "${tmp}" || {
    echo "could not write herdr web ui env; continuing" >&2
    return 0
  }
  chmod 600 "${tmp}" 2>/dev/null || true
  if [ -f "${file}" ]; then
    while IFS= read -r line || [ -n "${line}" ]; do
      trimmed="${line#"${line%%[![:space:]]*}"}"
      key="${trimmed%%=*}"
      key="${key%"${key##*[![:space:]]}"}"
      case "${key}" in
        HOST|PORT)
          ;;
        *)
          printf '%s\n' "${line}" >> "${tmp}" || {
            echo "could not write herdr web ui env; continuing" >&2
            rm -f "${tmp}" || true
            return 0
          }
          ;;
      esac
    done < "${file}"
  fi
  printf 'HOST=%s\nPORT=%s\n' "${HERDR_WEB_BIND}" "${HERDR_WEB_PORT}" >> "${tmp}" || {
    echo "could not write herdr web ui env; continuing" >&2
    rm -f "${tmp}" || true
    return 0
  }
  chmod 600 "${tmp}" || echo "could not chmod herdr web ui env; continuing" >&2
  if ! mv -f "${tmp}" "${file}"; then
    echo "could not replace herdr web ui env; continuing" >&2
    rm -f "${tmp}" || true
    return 0
  fi
  chmod 600 "${file}" || echo "could not chmod herdr web ui env; continuing" >&2
  return 0
}

start_embedded_herdr() {
  if ! command -v herdr >/dev/null 2>&1; then
    echo "herdr is missing; continuing without embedded herdr" >&2
    return 0
  fi

  # Write before herdr server so its startup hook sees HOST and PORT.
  write_web_ui_env

  if herdr_status; then
    echo "herdr server already running; not starting a second server" >&2
  else
    echo "starting herdr server" >&2
    herdr server >>/tmp/herdr-server.log 2>&1 &
  fi

  # Wait up to about 10 seconds before the plugin invoke. A hung status is bounded.
  ready=0
  deadline=$((SECONDS + 10))
  while [ "${SECONDS}" -le "${deadline}" ]; do
    if herdr_status; then
      ready=1
      break
    fi
    if [ "${SECONDS}" -ge "${deadline}" ]; then
      break
    fi
    sleep 1
  done
  if [ "${ready}" -ne 1 ]; then
    echo "herdr server not ready after about 10s; continuing" >&2
  fi

  write_web_ui_env
  echo "starting herdr web ui" >&2
  (
    if ! HOST="${HERDR_WEB_BIND}" PORT="${HERDR_WEB_PORT}" herdr plugin action invoke devswha.herdr-web-ui.start >>/tmp/herdr-web.log 2>&1; then
      echo "herdr web ui start failed; see /tmp/herdr-web.log" >&2
    fi
  ) &
  return 0
}

case "${HERDR_MODE}" in
  embedded)
    start_embedded_herdr || echo "embedded herdr setup failed; continuing" >&2
    ;;
  external|off)
    echo "HERDR_MODE=${HERDR_MODE}; not starting herdr" >&2
    ;;
  *)
    echo "unknown HERDR_MODE=${HERDR_MODE}; not starting herdr" >&2
    ;;
esac

exec uvicorn app.main:app --host "${DASHBOARD_HOST:-0.0.0.0}" --port "${DASHBOARD_PORT:-8080}"
