#!/usr/bin/env bash
# 在 Linux 环境构建云函数部署包（regardless of 本机是 macOS）。
#
# 为什么需要它：numpy/pandas/lxml/curl_cffi 等含 C 扩展的二进制包，在 macOS 上装的 .so
# 无法在云函数（Linux）运行；必须在 Linux 环境安装依赖后再打包。本脚本用 Docker 完成。
#
# 用法：
#   bash deploy/build_package.sh            # 默认 Python 3.9，产物 dist/function.zip
#   PY_VER=3.10 bash deploy/build_package.sh
#
# 前置：本机已装 Docker。
set -euo pipefail

PY_VER="${PY_VER:-3.9}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # 指向 src/
OUT_DIR="${SRC_DIR}/dist"
BUILD_DIR="${OUT_DIR}/build"

echo ">>> 源码目录: ${SRC_DIR}"
echo ">>> Python 版本: ${PY_VER}"

rm -rf "${BUILD_DIR}" "${OUT_DIR}/function.zip"
mkdir -p "${BUILD_DIR}"

# 1) 在 Linux 容器内安装依赖到 build 目录（--target 使依赖与代码平铺，云函数可直接 import）
docker run --rm \
  -v "${SRC_DIR}":/src \
  -v "${BUILD_DIR}":/build \
  "python:${PY_VER}-slim" \
  bash -c "pip install --no-cache-dir -r /src/requirements.txt -t /build"

# 2) 拷贝业务代码（排除测试、缓存、密钥、构建产物）
cp "${SRC_DIR}"/*.py "${BUILD_DIR}/"
cp "${SRC_DIR}/indices.json" "${BUILD_DIR}/"
rm -rf "${BUILD_DIR}/__pycache__"

# 3) 打 zip（注意：zip 内是平铺结构，main.py 在根，云函数入口填 main.main_handler）
cd "${BUILD_DIR}"
zip -rq "${OUT_DIR}/function.zip" . -x "*.pyc" -x "*__pycache__*"
cd - >/dev/null

echo ">>> 打包完成: ${OUT_DIR}/function.zip"
du -sh "${OUT_DIR}/function.zip"
echo ">>> 云函数入口填: main.main_handler"
