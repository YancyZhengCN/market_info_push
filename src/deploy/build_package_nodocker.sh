#!/usr/bin/env bash
# 不依赖 Docker 的打包方式：用 pip 直接下载 Linux 平台 wheel，在 macOS 上也能打出云函数包。
#
# 背景：pip 跨平台安装（--platform）必须配 --only-binary=:all:，但 akshare 的部分纯 Python
# 依赖（如 jsonpath）没有 wheel，无法满足 :all:。且不同二进制包的 manylinux 版本 tag 不同
# （numpy/pandas 是 manylinux2014/glibc2.17，mini-racer 只有 manylinux_2_31/glibc2.31）。
# 故分三步：
#   步骤1：常规安装全部依赖（正确解析纯 Python 依赖，此时二进制是 macOS 版）；
#   步骤2：用 Linux wheel 覆盖 numpy/pandas/lxml/curl_cffi/cffi（manylinux2014）；
#   步骤3：用 Linux wheel 覆盖 mini-racer（manylinux_2_31，其 V8 原生库 tag 较新）。
# 覆盖式安装把 macOS 二进制换成 Linux 版，纯 Python 代码跨平台通用。
#
# 前提：云函数运行时（SCF/FC Python 3.9）底层 glibc >= 2.31，可运行上述 wheel。
# 局限：若拉取的 wheel tag 与目标运行时 glibc 不匹配，改用 build_package.sh（Docker）最稳妥。
#
# 用法：
#   bash deploy/build_package_nodocker.sh
#   PY_VER=39 bash deploy/build_package_nodocker.sh   # 目标 Python 3.9（默认）
set -euo pipefail

PY_ABI="${PY_VER:-39}"                 # 云函数运行时 Python，如 39 / 310
PLATFORM="manylinux2014_x86_64"        # 多数二进制包（x86_64 云函数）；ARM 改 manylinux2014_aarch64
PLATFORM_NEW="manylinux_2_31_x86_64"   # mini-racer 专用（glibc2.31）；ARM 改 manylinux_2_31_aarch64
BINARY_PKGS=(numpy pandas lxml curl_cffi cffi simplejson charset-normalizer)   # manylinux2014 系
NEWLIBC_PKGS=(mini-racer)                        # manylinux_2_31 系
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${SRC_DIR}/dist"
BUILD_DIR="${OUT_DIR}/build"

echo ">>> 源码目录: ${SRC_DIR}"
echo ">>> 目标平台: ${PLATFORM} (+ ${PLATFORM_NEW} for mini-racer) / Python ${PY_ABI}"

rm -rf "${BUILD_DIR}" "${OUT_DIR}/function.zip"
mkdir -p "${BUILD_DIR}"

# 步骤1：常规安装全部依赖（解析并装齐纯 Python 依赖；二进制此刻是本机 macOS 版，稍后覆盖）
echo ">>> [1/3] 常规安装全部依赖"
python3 -m pip install --target "${BUILD_DIR}" -r "${SRC_DIR}/requirements.txt"

# 步骤2：用 Linux wheel 覆盖含 C 扩展的包（manylinux2014）
echo ">>> [2/3] 覆盖为 Linux wheel: ${BINARY_PKGS[*]}"
python3 -m pip install \
  --platform "${PLATFORM}" --python-version "${PY_ABI}" \
  --implementation cp --only-binary=:all: --no-deps \
  --target "${BUILD_DIR}" --upgrade \
  "${BINARY_PKGS[@]}"

# 步骤3：用 Linux wheel 覆盖 mini-racer（manylinux_2_31，V8 原生库）
# 注：mini-racer 的 Linux wheel 可能仅在官方 PyPI 提供，故显式指定官方源。
#     mini-racer 从官方 PyPI 跨境下载约 15MB、耗时数分钟，是整个打包最慢的一步；
#     故此处（及步骤1/2）不加 --no-cache-dir，让 pip 复用本地缓存，重建时无需重复下载。
echo ">>> [3/3] 覆盖为 Linux wheel: ${NEWLIBC_PKGS[*]}"
python3 -m pip install \
  --index-url https://pypi.org/simple/ \
  --platform "${PLATFORM_NEW}" --python-version "${PY_ABI}" \
  --implementation cp --only-binary=:all: --no-deps \
  --target "${BUILD_DIR}" --upgrade \
  "${NEWLIBC_PKGS[@]}"

# 2) 拷贝业务代码
cp "${SRC_DIR}"/*.py "${BUILD_DIR}/"
cp "${SRC_DIR}/indices.json" "${BUILD_DIR}/"
rm -rf "${BUILD_DIR}/__pycache__"

# 2.5) 清理 macOS 残留二进制：覆盖安装时若 Linux wheel 的 .so 文件名与本机 darwin 版不同，
#      旧的 darwin .so 不会被删除而残留。这里统一删掉所有 *-darwin.so，避免污染 Linux 包。
echo ">>> 清理 macOS 残留二进制(*-darwin.so)"
find "${BUILD_DIR}" -name "*-darwin.so" -print -delete || true
# 兜底：扫描是否仍有 Mach-O 文件，有则报错中止（避免上传不可用的包）
if find "${BUILD_DIR}" -name "*.so" -exec file {} \; 2>/dev/null | grep -qi "mach-o"; then
  echo "!!! 仍存在 macOS(Mach-O)二进制，包不可用，请改用 build_package.sh(Docker)" >&2
  find "${BUILD_DIR}" -name "*.so" -exec file {} \; 2>/dev/null | grep -i "mach-o" >&2
  exit 1
fi

# 3) 打 zip（平铺结构，入口 main.main_handler）
cd "${BUILD_DIR}"
zip -rq "${OUT_DIR}/function.zip" . -x "*.pyc" -x "*__pycache__*"
cd - >/dev/null

echo ">>> 打包完成: ${OUT_DIR}/function.zip"
du -sh "${OUT_DIR}/function.zip"
echo ">>> 云函数入口填: main.main_handler"
