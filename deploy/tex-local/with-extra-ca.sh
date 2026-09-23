#!/bin/sh
# TEX Engine local image - build-time helper (not used at runtime).
#
# Runs a command that downloads something (pip, uv, git, yarn) and, only when the
# optional BuildKit secret "extra_ca" is mounted, makes it trust that extra root CA
# as well as the normal ones. That is needed on networks whose proxy re-signs TLS
# (some corporate networks). Without the secret the command runs unchanged.
# The CA is never copied into the image: the combined bundle lives in /tmp for the
# duration of the command and is deleted afterwards.
set -eu

ca=/run/secrets/extra_ca
if [ ! -s "$ca" ]; then
	exec "$@"
fi

bundle="$(mktemp)"
cat /etc/ssl/certs/ca-certificates.crt "$ca" > "$bundle"
export SSL_CERT_FILE="$bundle" REQUESTS_CA_BUNDLE="$bundle" CURL_CA_BUNDLE="$bundle" \
	GIT_SSL_CAINFO="$bundle" PIP_CERT="$bundle" NODE_EXTRA_CA_CERTS="$ca" \
	UV_SYSTEM_CERTS=1 UV_NATIVE_TLS=1
set +e
"$@"
rc=$?
rm -f "$bundle"
exit "$rc"
