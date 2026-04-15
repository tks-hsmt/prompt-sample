# build
```
$ docker build -f test/Dockerfile -t fluentd-plugin-test .
```

# test
```
$ docker run --rm fluentd-plugin-test

Loaded suite /work/test
Started
................
Finished in 0.567 seconds.
----------------------------------------
16 tests, 24 assertions, 0 failures, 0 errors
100% passed
```
# 個別テスト
```
$ docker run --rm \
  -v "$(pwd)/files/plugins:/work/files/plugins:ro" \
  -v "$(pwd)/test:/work/test:ro" \
  fluentd-plugin-test \
  bundle exec ruby test_filter_timestamp_normalize.rb
```
