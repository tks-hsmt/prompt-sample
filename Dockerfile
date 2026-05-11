# syntax=docker/dockerfile:1.7
FROM node:24-slim

# OpenSpec は Node.js 20.19.0 以上を要求
# node:24 は 2025年10月から Active LTS(コードネーム Krypton)で、Active LTS は 2026年10月まで
# https://github.com/Fission-AI/OpenSpec#quick-start
# https://github.com/nodejs/Release

# OpenSpec を npm でグローバルインストール(イメージビルド時、root として実施)
# 最新バージョンは https://www.npmjs.com/package/@fission-ai/openspec で確認
RUN npm install -g @fission-ai/openspec@latest

# ホストとの UID/GID 衝突を避けるため、既存の node ユーザーの UID/GID を調整
ARG USER_ID=1000
ARG GROUP_ID=1000
RUN if [ "${GROUP_ID}" != "1000" ]; then groupmod -g ${GROUP_ID} node; fi \
    && if [ "${USER_ID}" != "1000" ]; then usermod -u ${USER_ID} -g ${GROUP_ID} node; fi

# OpenSpec のグローバル設定ディレクトリを node 所有で事前作成
# (ホスト側ディレクトリを bind mount する際の権限問題を防ぐため)
# OpenSpec のデフォルト設定パスは ~/.config/openspec/config.json
RUN mkdir -p /home/node/.config/openspec \
    && chown -R node:node /home/node/.config

USER node
WORKDIR /workspace

# テレメトリーを無効化(任意。CI 環境では自動で無効化される)
# https://github.com/Fission-AI/OpenSpec#telemetry
ENV OPENSPEC_TELEMETRY=0

CMD ["bash"]