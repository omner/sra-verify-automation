#!/usr/bin/env bash
# Builds the sraverify Lambda layer zip.
# Run this before `terraform apply`.
#
# Usage: ./scripts/build-layer.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_DIR/terraform/.build"
LAYER_DIR="$BUILD_DIR/layer"

echo "==> Cleaning previous build..."
rm -rf "$LAYER_DIR"
mkdir -p "$LAYER_DIR/python" "$BUILD_DIR"

echo "==> Installing sraverify and dependencies into layer..."
pip install \
  git+https://github.com/awslabs/sra-verify.git#subdirectory=sraverify \
  --target "$LAYER_DIR/python" \
  --quiet

echo "==> Creating layer zip..."
cd "$LAYER_DIR"
zip -r "$BUILD_DIR/sraverify-layer.zip" python/ -q

echo "==> Layer built: $BUILD_DIR/sraverify-layer.zip"
echo "    Size: $(du -h "$BUILD_DIR/sraverify-layer.zip" | cut -f1)"
