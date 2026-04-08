# エラー対応リファレンス

このファイルは Phase 4 の検証で失敗が発生した場合のみ読み込む。

## 目次

1. [検証は必ず scripts/validate-chart.sh を使う](#検証は必ず-scriptsvalidate-chartsh-を使う)
2. [validate-chart.sh が実行する検証](#validate-chartsh-が実行する検証)
3. [よくあるエラーと対処](#よくあるエラーと対処)
4. [エラー対応の判断フロー](#エラー対応の判断フロー)
5. [検証成功時の確認事項](#検証成功時の確認事項)

## 検証は必ず scripts/validate-chart.sh を使う

**重要**: 個別に `helm lint` 等を実行してはならない。複数ユーザー間でのテスト一貫性のため、必ず `scripts/validate-chart.sh` を使用する。

```bash
bash scripts/validate-chart.sh <chart-dir>
```

## validate-chart.sh が実行する検証

| # | 検証 | 失敗時の意味 |
|---|---|---|
| 1 | CHARTNAME 残存チェック | `copy-template.sh` の置換漏れ |
| 2 | YAML 構文検証 | values 系ファイルの YAML 構文エラー |
| 3 | JSON Schema 検証 | values.yaml が schema に違反 |
| 4 | helm lint | チャート構文エラー、推奨事項違反（helm 利用可能時） |
| 5-7 | helm template 各環境 | レンダリング失敗（helm 利用可能時） |

`helm` コマンドが利用できない場合は `--no-helm` オプションで Python ベース検証のみ実行する。

## よくあるエラーと対処

### Error 1: image.repository または image.digest が空

```
ValidationError: '' is too short
Failed validating 'minLength' in schema['properties']['image']['properties']['repository']
```

または

```
ValidationError: '' does not match '^sha256:[a-f0-9]{64}$'
```

**原因**: ヒアリングフェーズで取得した repository / digest が values.yaml に反映されていない

**対処**:
1. 計画ファイルの `image.repository` および `image.digest` の値を確認
2. `values.yaml` の該当箇所を計画通りに設定
3. digest 形式が `sha256:` で始まり 64 桁の 16 進数であることを確認
4. 再検証

**digest の取得方法**:
```bash
# Docker
docker inspect <image>:<tag> --format='{{index .RepoDigests 0}}'

# crane (go-containerregistry)
crane digest <image>:<tag>

# skopeo
skopeo inspect docker://<image>:<tag> | jq -r '.Digest'
```

### Error 2: CHARTNAME が残存

```
template: my-chart/templates/deployment.yaml:4:11: error calling include: 
template: no template "CHARTNAME.fullname" associated with template
```

**原因**: `copy-template.sh` の CHARTNAME 置換が一部で失敗、または手動で追加したファイルに CHARTNAME が含まれている

**対処**:
1. 全ファイルで CHARTNAME を grep する: `grep -r CHARTNAME <chart-dir>/`
2. 残存箇所を実際のチャート名に置換
3. 再検証

### Error 3: probes の port が解決できない

```
Error: failed to get port: port name "http" not found
```

**原因**: probes の `port` と `service.portName` が一致していない

**対処**:
1. `values.yaml` の `service.portName` を確認
2. `livenessProbe.httpGet.port` と `readinessProbe.httpGet.port` を `service.portName` と同じ値に修正
3. 再検証

### Error 4: CronJob の schedule が空

```
ValidationError: '' is too short
Failed validating 'minLength' in schema['properties']['schedule']
```

**原因**: ヒアリングで取得した schedule が values.yaml に反映されていない

**対処**:
1. 計画ファイルの `schedule` の値を確認
2. `values.yaml` の `schedule` を cron 式で設定
3. 再検証

### Error 5: StatefulSet の persistence で StorageClass エラー

```
Error: storageclass.storage.k8s.io "" not found
```

**原因**: クラスタにデフォルト StorageClass が設定されていない、または `persistence.storageClass` が空

**対処**:
1. ユーザーに使用する StorageClass を確認
2. `values.yaml` または `values-prod.yaml` の `persistence.storageClass` を設定
3. 再検証

### Error 6: Service の targetPort が見つからない

```
Error: service "my-app" has no targetPort matching named port "http"
```

**原因**: `service.portName` を変更した後、Service テンプレートで参照が更新されていない

**対処**:
1. `service.portName` の値を確認
2. テンプレートが値を正しく参照しているか確認（`templates/service.yaml`）
3. 通常はテンプレート修正不要 — values.yaml 側の `portName` を統一すれば解決

### Error 7: Pod Security Standards 違反

```
Error: pods "my-app-xxx" is forbidden: violates PodSecurity "restricted:v1.28"
```

**原因**: Pod Security Standards Restricted プロファイルに違反する設定

**対処**: 通常はテンプレートのデフォルトで遵守されているはず。values.yaml で `podSecurityContext` や `containerSecurityContext` を上書きしていないか確認。上書きが必要ない限り、デフォルトを維持すること。

### Error 8: helm lint の警告（icon, sources, maintainers）

```
[INFO] Chart.yaml: icon is recommended
[INFO] Chart.yaml: maintainers are recommended
```

**対処**: これは情報レベルなので無視可能。本番運用では `Chart.yaml` に `maintainers` を追加することを検討。

## エラー対応の判断フロー

```
検証失敗
   │
   ├─ 同じエラーが初回？
   │   ├─ Yes → エラー対応表を参照して修正、再検証
   │   └─ No → 同じエラーが 2 回目？
   │       ├─ Yes → エラー対応表の対処を再確認、別の角度で修正、再検証
   │       └─ No → 同じエラーが 3 回目 → Phase 1c に戻る（要件理解の誤りの可能性）
   │
   └─ 別のエラー？
       └─ → 初回として対応
```

## 検証成功時の確認事項

`validate-chart.sh` が成功しても、以下を最終確認する:

1. **生成されたマニフェストに CHARTNAME が残っていない**
   ```bash
   helm template <chart-dir> | grep CHARTNAME
   # 出力なしが正常
   ```

2. **生成されたマニフェストにダミー値が混入していない**
   ```bash
   helm template <chart-dir> | grep -E '(localhost|example.com|TODO)'
   # 出力なしが正常
   ```

3. **計画ファイルに記載した変更が全て反映されている**
   - 計画ファイルの「決定方法」列が `ユーザー指定` または `ユースケース判定` の項目を 1 つずつ目視確認
