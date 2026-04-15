# 本番と同じFluentdイメージをベースにする
# これによりRuby/FluentdのバージョンがずれずAPIの互換性が保証される
FROM fluent/fluentd-kubernetes-daemonset:v1.19-debian-forward-2

# Fluentd公式イメージは fluent ユーザーで動くので、
# gem install のためだけ一時的にrootに戻る
USER root

# ネイティブ拡張を含むgem(test-unit等)のビルドに必要
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /work/test

# Gemfileを先にコピーしてinstallすることで、
# プラグインコード変更時のビルドキャッシュを有効化
COPY test/Gemfile test/Gemfile.lock* ./
RUN bundle install

# プラグイン本体とテストコードをコピー
# (docker run時に-vマウントで上書き可能)
COPY files/plugins /work/files/plugins
COPY test /work/test

CMD ["bundle", "exec", "rake", "test"]