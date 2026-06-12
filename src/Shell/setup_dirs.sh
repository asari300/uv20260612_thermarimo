#!/usr/bin/env bash
# data/ 配下のディレクトリ構成を構築する。
#
# data/ は .gitignore 対象のため git clone 直後には存在しない。その対策として
# clone 後の初回に実行する（既存環境で実行しても無害・冪等）。
# なお main.py / scheduler 起動時にも Python 側（storage.ensure_data_dirs）で
# 同じ構成が自動生成される。
#
# 使い方: bash src/Shell/setup_dirs.sh

set -euo pipefail

# スクリプト位置からリポジトリルートへ移動（実行時の cwd に依存しない）
cd "$(dirname "$0")/../.."

# 保存先: {範囲}h{間隔}s = {012,024,168,ALL} × {001,005,010,060,300} の20ディレクトリ
for hours in 012 024 168 ALL; do
    for seconds in 001 005 010 060 300; do
        mkdir -p "data/${hours}h${seconds}s"
    done
done

# 診断スクリプト（scripts/fetch_raw.py）の生レスポンス保存先
mkdir -p data/raw

count=$(find data -mindepth 1 -maxdepth 1 -type d | wc -l)
echo "data/ ディレクトリ構成を作成しました（${count} ディレクトリ）"
