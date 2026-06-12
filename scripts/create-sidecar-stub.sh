#!/usr/bin/env bash
set -euo pipefail

# Creates a placeholder sidecar executable so Tauri can compile before the
# PyInstaller backend sidecar exists. Replace with scripts/build_backend_sidecar.py output.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="$ROOT/frontend/src-tauri/binaries"
mkdir -p "$BIN_DIR"

write_stub() {
  local name="$1"
  cat >"$BIN_DIR/$name" <<'EOF'
#!/usr/bin/env bash
echo "rhapsode-backend sidecar missing: run uv run python scripts/build_backend_sidecar.py" >&2
exit 1
EOF
  chmod +x "$BIN_DIR/$name"
  echo "stub -> $BIN_DIR/$name"
}

case "$(uname -s)" in
  Darwin)
    write_stub "rhapsode-backend-aarch64-apple-darwin"
    write_stub "rhapsode-backend-x86_64-apple-darwin"
    ;;
  MINGW* | MSYS* | CYGWIN* | Windows*)
    write_stub "rhapsode-backend-x86_64-pc-windows-msvc.exe"
    ;;
  *)
    echo "Unsupported host OS for sidecar stub: $(uname -s)" >&2
    exit 1
    ;;
esac
