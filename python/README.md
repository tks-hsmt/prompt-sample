# DR 切替 Lambda 実装メモ

## エラー処理の契約

Step Functions が区別する必要があるのは 2 つだけ。

| 例外 | 意味 | ASL 側 |
|---|---|---|
| `RetryableError` | 一時的。または「まだ収束していない」 | `Retry` |
| `ContinuableError` | 失敗したが作業継続してよい（旧 ACTIVE 側の閉塞失敗） | `Catch` |
| （型を定義しない） | それ以外すべて | 何にもマッチせず**ワークフロー停止** |

「止めるべきエラー」に独自の型は定義しない。`Retry` にも `Catch` にも
マッチしない例外は Step Functions が失敗させるため、停止はデフォルトの
挙動である。設定不備や権限不足はバグであり、未捕捉例外として止まるのが
正しい。`ConfigError` / `FatalError` / `PermanentFailure` のような型は作らない。

`raise_classified()` の振り分け:

| best_effort | エラー | 結果 |
|---|---|---|
| — | スロットリング・接続断・タイムアウト | `RetryableError` |
| `True` | その他の AWS エラー | `ContinuableError` |
| `False` | その他の AWS エラー | 元の例外をそのまま送出（停止） |

`best_effort` は**操作の性質**。閉塞は失敗しても切替を続けるため `True`、
開放は失敗したら切替が成立しないため `False`。ハンドラの宣言に書く。

```python
@lambda_handler("apigateway-block",  ApiGatewayConfig, best_effort=True)
@lambda_handler("apigateway-enable", ApiGatewayConfig)
```

AWS SDK 以外の例外（`KeyError` 等）は分類せず素通しさせる。自分のコードの
バグをインフラ障害に化けさせないため。

### 捕捉はデコレータに集約する

AWS 例外の `try/except` は `lambda_handler` の中だけに置き、個々のハンドラでは
書かない。

- 分類の判断材料はエラーコードと role の 2 つで、どちらもデコレータが
  持っている。個々の操作側で捕捉しても情報を足せず catch-and-rethrow になる
- 操作系を追加した人が `try/except` を書き忘れると、PEER 側の恒久エラーが
  `ContinuableError` にならずワークフローを止める。集約すればこの失敗モード
  自体が消える

### 複数インスタンスのループは `run_per_item` に統一

操作系の Lambda は「リソース種別」を担当し、その中の個別インスタンス
（バケット、スケジュール）はループで処理する。`dr_switch.core.errors.run_per_item()` が
その集約を担う。

- **1 件失敗しても残りを必ず試みる。** 最初の失敗で中断すると、止められた
  はずの残りが開いたままになる。閉塞では止められた分だけリスクが減るため、
  部分的な成功に価値がある
- 一時エラーが 1 つでも混ざれば `RetryableError`（操作は冪等なので全体
  再試行で問題ない）、恒久エラーのみなら `ContinuableError`
- `role=self` の恒久エラーは `raise_classified` が元の例外をそのまま送出
  するため、内側の `except` に捕まらず即座に停止する
- 自分のコードのバグ（`KeyError` 等）は分類せず素通し

`dr_switch.scheduler` と `dr_switch.s3` は同じ性質の操作なので、同じヘルパを使う。
一覧取得（`list_schedules`）の失敗は 1 件の失敗ではないので、ループの外に
置いて `lambda_handler` に分類させる。

観測系の check ハンドラは揃えない。AWS エラーが出るのは権限不足やリソース不在＝
バグで、続けても意味がないため中断が妥当。「未収束」の問題はループが正常に
回りきってから全件まとめて送出するので、集約は既に効いている。

## 横断処理はデコレータ

`dr_switch/core/middleware.py` の `lambda_handler` が、設定読み込み・ログ・
AWS 例外の分類を担う。各ハンドラは自分の処理だけを書く。

```python
@lambda_handler("nlb-check", NlbCheckConfig)
def check(cfg: NlbCheckConfig, event: dict, *, dry_run: bool, context) -> dict:
    return problems   # 問題のある項目だけを返す。正常なら {}


@lambda_handler("apigateway-block", ApiGatewayConfig, best_effort=True)
def block(cfg: ApiGatewayConfig, event: dict, *, dry_run: bool, context) -> dict:
    _set_throttle(...)
    return {}
```

### 契約

    成功                     -> 何も返さない
    一時的な失敗・未収束     -> RetryableError
    継続してよい失敗         -> ContinuableError
    待っても解消しない状態   -> NotRecoverableError
    それ以外                 -> 元の例外をそのまま送出

`NotRecoverableError` はハンドラが自分で判定して送出する。Retry にも Catch にも
マッチしないのでワークフローが止まる。「まだ収束していない」と区別するのが目的で、
これが無いと解消しない状態をリトライ上限（30 秒 × 10 回 = 5 分）まで待ってから
失敗することになり、RTO を無駄にする。

| ハンドラ | 待てば直る（RetryableError） | 待っても直らない（NotRecoverableError） |
|---|---|---|
| lambda | `Pending` / `LastUpdateStatus: InProgress` | `Inactive` / `Failed` / `LastUpdateStatus: Failed` |
| dynamodb | `CREATING` / `UPDATING` | `DELETING` / `ARCHIVED` など |
| s3 | ルールが `Disabled` | レプリケーション設定が存在しない |
| eks | `readyReplicas` 不足 / Pending Pod | DaemonSet の `desiredNumberScheduled == 0` |
| nlb | `initial` が残っている | — |
| apigateway | `apiStatus: PENDING` / スロットリング未復元 | `apiStatus: FAILED` |

**操作系と観測系でデコレータを分けない。** 呼び出し元は例外の有無だけで
判断するので、契約は同一になる。分けていたときは観測系が AWS 例外を素通しして
おり、スロットリングでワークフローが止まる不整合があった。

**「何をしたか」は返さない。** 実行前から決まっているうえ、呼び出し元が
参照しない。障害調査に必要な情報はログに出す。

戻り値は「問題のある項目」だけを表す。処理を実行するだけの関数は常に空を返す。

## 構成

**リソース単位のパッケージ**に統一する。1 つのリソースに関する設定・閉塞・
開放・確認がすべて同じディレクトリに集まり、リソースを追加するときに増えるのは
ディレクトリ 1 つになる。

```
dr_switch/
  core/                    # リソースに依存しない共通部分
    aws.py                 # boto3 クライアント（BOTO_CONFIG）
    config.py              # 環境変数ヘルパと BaseConfig
    errors.py              # 例外の分類と集約（run_per_item を含む）
    middleware.py          # lambda_handler
  apigateway/
    config.py  handlers.py    # block / enable / check
  scheduler/
    config.py  handlers.py    # block / enable
  s3/
    config.py  handlers.py    # block / enable / check
  lambda_function/
    config.py  handlers.py    # check
  dynamodb/
    config.py  handlers.py    # check
  nlb/
    config.py  handlers.py    # check
  cloudwatch/
    config.py  handlers.py    # check
  eks/
    config.py  handlers.py    # restart_pods / rollout_restart / check
  efs/
    config.py  handlers.py    # check
tests/
Dockerfile
```

### ディレクトリ名の規則

**boto3 のクライアント名**を使う。コード中の `client("apigateway", ...)` と
ディレクトリ名が一致し、恣意的な略語を作らずに済む。例外は 2 つ。

| ディレクトリ | 理由 |
|---|---|
| `lambda_function` | `lambda` は Python の予約語。PEP 8 は予約語衝突の回避として「同義語を使う」を最善、「末尾アンダースコア」を次善、「略語や綴りの改変」を最悪としており、最善を採った |
| `nlb` | boto3 名の `elbv2` は API 名で確認対象（NLB のターゲットグループ）を表さない。NLB は AWS 自身が使う略称 |

自分で略語を作らない、という規則。S3 / EKS / NLB は AWS の公式表記なのでそのまま使う。

### ハンドラ

| 関数 | ハンドラ | 種別 | 対象リージョン |
|---|---|---|---|
| dr-apigateway-block | `dr_switch.apigateway.handlers.block` | 変更 | 閉塞対象 |
| dr-apigateway-enable | `dr_switch.apigateway.handlers.enable` | 変更 | 自リージョン |
| dr-apigateway-check | `dr_switch.apigateway.handlers.check` | 観測 | 自リージョン |
| dr-scheduler-block | `dr_switch.scheduler.handlers.block` | 変更 | 閉塞対象 |
| dr-scheduler-enable | `dr_switch.scheduler.handlers.enable` | 変更 | 自リージョン |
| dr-scheduler-check | `dr_switch.scheduler.handlers.check` | 観測 | 自リージョン |
| dr-s3-block | `dr_switch.s3.handlers.block` | 変更 | 閉塞対象 |
| dr-s3-enable | `dr_switch.s3.handlers.enable` | 変更 | 自リージョン |
| dr-s3-check | `dr_switch.s3.handlers.check` | 観測 | 自リージョン |
| dr-lambda-check | `dr_switch.lambda_function.handlers.check` | 観測 | 自リージョン |
| dr-dynamodb-check | `dr_switch.dynamodb.handlers.check` | 観測 | 自リージョン |
| dr-nlb-check | `dr_switch.nlb.handlers.check` | 観測 | 自リージョン |
| dr-cloudwatch-check | `dr_switch.cloudwatch.handlers.check` | 観測 | 自リージョン |
| dr-eks-restart-pods | `dr_switch.eks.handlers.restart_pods` | 変更 | 自リージョン |
| dr-eks-rollout-restart | `dr_switch.eks.handlers.rollout_restart` | 変更 | 自リージョン |
| dr-eks-check | `dr_switch.eks.handlers.check` | 観測 | 自リージョン |
| dr-efs-check | `dr_switch.efs.handlers.check` | 観測 | 自リージョン |

`dr_switch.s3.handlers` の block / enable は **S3 案 A を採用する場合のみ**デプロイする。

閉塞と開放を別関数に分けているため、入力は `{"dry_run": bool}` のみ
（`apigateway.enable` だけ任意で `throttle` を受ける）。どちらのリージョンを
対象にするかは環境変数で決まる。

### 設定クラスの単位

**リソースごとに Base を置き、ハンドラごとにサブクラスを作る。** 追加項目が
無いハンドラでも空のサブクラスを定義し、全リソースで構造を揃える。

```python
class ApiGatewayBaseConfig(BaseConfig):     # 全ハンドラ共通
    rest_api_id: str
    stage: str

class ApiGatewayBlockConfig(ApiGatewayBaseConfig):
    """block 用。閉塞は定数 0 を使うので追加の項目は無い。"""

class ApiGatewayEnableConfig(ApiGatewayBaseConfig):
    throttle_rate: float
    throttle_burst: int

class ApiGatewayCheckConfig(ApiGatewayEnableConfig):
    """check 用。enable が設定した値と一致するかを確認する。"""
```

| リソース | Base | サブクラス |
|---|---|---|
| apigateway | `ApiGatewayBaseConfig` | Block / Enable / Check |
| scheduler | `SchedulerBaseConfig` | Block / Enable / Check |
| s3 | `S3BaseConfig` | Block / Enable / Check |
| lambda_function | `LambdaBaseConfig` | Check |
| dynamodb | `DynamoDbBaseConfig` | Check |
| nlb | `NlbBaseConfig` | Check |
| cloudwatch | `AlarmBaseConfig` | Check |
| efs | `EfsBaseConfig` | Check |
| eks | `EksBaseConfig` | RolloutRestart / Check |
| eks（Lambda 呼び出し） | `PodRestartBaseConfig` | PodRestart |

**差分が無くてもサブクラスを作る理由は、読み手が例外を覚えなくてよいこと。**
「なぜここだけ分かれているのか」を構造の外で説明しなければならない状態を避ける。
将来ハンドラ固有の項目が増えたときも置き場所が既にある。

`PodRestartBaseConfig` だけは別系統。EKS のリソースではなく**呼び出す Lambda
関数**を指すので、`EksBaseConfig` とは概念が違う。

分けた実利は、**必要な項目を `_required` にできる**こと。`THROTTLE_RATE` は
`ApiGatewayEnableConfig` の必須なので、設定漏れが `from_env` で止まる。
`block` 用の Lambda には渡す必要が無いことも構造から読み取れる。

### core のファサード

`dr_switch/core/__init__.py` が公開する名前を再エクスポートする。各リソースの
import が 1 行で済む。

```python
from dr_switch.core import client, lambda_handler
```

**`dr_switch/core/` の内部は必ずフルパスで import する**（`from
dr_switch.core.errors import ...`）。ファサード経由にすると、`__init__.py` が
サブモジュールを読み込む途中で参照が発生し、依存が一方向でも
「partially initialized module」の循環エラーになる。しかも `__init__.py` の
記述順によって発生したりしなかったりする。

なおこれは特別なルールではなく、PEP 8 が推奨する絶対 import そのもの。

### handlers.py に配線とロジックを同居させる理由

AWS が明文化しているのは「ハンドラをコアロジックから分離する」で、これが
要求しているのは**関数の分離**であってファイルの分離ではない。デコレータで
包まれた関数の中身には `__wrapped__` で到達できるため、テスト可能性は
満たされる。

`service.py` を別ファイルにするかは SRP（変更理由の分離）で判断できるが、
20〜40 行のモジュールでは判定できる規模にない。`handlers.py` が 100 行を
超えたリソースが出てきたら、そのとき判断材料が揃う。

### ログ

ログの初期化と呼び出しコンテキストの注入は、既存の共通モジュール
`common_logger` の `setup_logging` / `inject_lambda_context` に委ねる。
`middleware.py` は標準の `logging.getLogger(__name__)` を使うだけで、
ロガーの設定は行わない。

```python
@inject_lambda_context
@lambda_handler("nlb-check", NlbCheckConfig)
def check(cfg: NlbCheckConfig, event: dict, *, dry_run: bool, context) -> dict:
    ...
```

`inject_lambda_context` は `lambda_handler` の**外側**に置く。内側に置くと
シグネチャが合わず実行時に TypeError になる。

## デプロイ（コンテナイメージ）

既存の Lambda に合わせてコンテナイメージでデプロイする。Layer は使わない。
17 本で同一イメージを共有し、ハンドラだけ変える。

```hcl
resource "aws_lambda_function" "nlb_check" {
  package_type = "Image"
  image_uri    = "${aws_ecr_repository.dr.repository_url}:${var.image_tag}"
  image_config {
    command = ["dr_switch.nlb.handlers.check"]
  }
  # ...
}
```

`dr_switch.eks` のみ VPC 設定が必要（既存の Pod 再起動 Lambda と同じ
サブネット・セキュリティグループ）。イメージには AWS CLI と
`kubernetes` パッケージを同梱している。

ログは既存の共通モジュール `common_logger` に委ねる（前述）。

## IAM（リソース単位）

観測系はすべて読み取り専用ロールにできる。変更系とは必ずロールを分けること。

関数を block / enable に分けたことで、**各関数の Resource は片側リージョン
だけで済む**。

| 関数 | 必要なアクション | Resource |
|---|---|---|
| dr-apigateway-block | `apigateway:GET` `apigateway:PATCH` | **閉塞対象**の `/restapis/<id>/stages/<stage>` |
| dr-apigateway-enable | `apigateway:GET` `apigateway:PATCH` | **自リージョン**の `/restapis/<id>/stages/<stage>` |
| dr-apigateway-check | `apigateway:GET` | 自リージョンの `/restapis/<id>` と `/restapis/<id>/stages/<stage>` |
| dr-scheduler-block | `scheduler:ListSchedules` `GetSchedule` `UpdateSchedule` `iam:PassRole` | **閉塞対象**の自チームグループのみ／スケジュール実行ロール |
| dr-scheduler-enable | 同上 | **自リージョン**の自チームグループのみ／スケジュール実行ロール |
| dr-scheduler-check | `scheduler:GetScheduleGroup` `scheduler:ListSchedules` | 自リージョンの自チームグループのみ |
| dr-s3-block | `s3:GetReplicationConfiguration` `PutReplicationConfiguration` `iam:PassRole` | **閉塞対象**のバケット／レプリケーションロール |
| dr-s3-enable | 同上 | **自リージョン**のバケット／レプリケーションロール |
| dr-s3-check | `s3:GetReplicationConfiguration` | 自リージョンのバケット |
| dr-lambda-check | `lambda:GetFunctionConfiguration` | 自リージョンの対象関数 |
| dr-dynamodb-check | `dynamodb:DescribeTable` | 自リージョンの対象テーブル |
| dr-nlb-check | `elasticloadbalancing:DescribeLoadBalancers` `DescribeTargetHealth` | `*` |
| dr-cloudwatch-check | `cloudwatch:DescribeAlarms` | `*` |
| dr-eks-restart-pods | `lambda:InvokeFunction` | 自リージョンの Pod 再起動関数 |
| dr-eks-rollout-restart | `eks:DescribeCluster` `sts:GetCallerIdentity` | 自リージョンのクラスタ／`*` |
| dr-eks-check | `eks:DescribeCluster` `sts:GetCallerIdentity` | 自リージョンのクラスタ／`*` |
| dr-efs-check | `elasticfilesystem:DescribeFileSystems` `DescribeMountTargets` | 自リージョンのファイルシステム |

東京・大阪は同一 AWS アカウント。両リージョンのリソースを同じ実行ロールで
操作できることを前提にしている。

注意点:

- `dr-scheduler-*` の `iam:PassRole` は必須。`UpdateSchedule` が
  `Target.RoleArn` を含む全パラメータを要求するため、これがないと失敗する。
  他のどの Lambda にも不要な権限なので見落としやすい
- `dr-scheduler-*` の Resource は自チーム専用グループに限定する。default
  グループには他チームのスケジュールが同居しているため、権限としても外す
- `dr-eks-check` のワークロード参照権限は IAM ではなく Kubernetes RBAC 側
  （EKS アクセスエントリで指定 namespace の RoleBinding）。Node を見ないので
  ClusterRoleBinding は不要
- S3 は SSE-S3（AES256）で SSE-C 禁止のため、KMS 関連の権限は全関数で不要

## 環境変数

各 Lambda には、その関数が操作・確認する**対象の値だけ**を渡す。閉塞系には
相手リージョンの値、開放系と観測系には自リージョンの値。どちらを渡すかは
Terraform 側で決まるため、コードは自他を区別しない
（`SELF_` / `PEER_` のプレフィックスは持たない）。

```hcl
# 東京側の Terraform

module "dr_apigw_block" {          # 大阪を閉塞する
  image_config_command = ["dr_switch.apigateway.handlers.block"]
  environment = {
    REGION      = "ap-northeast-3"
    REST_API_ID = var.osaka_rest_api_id
    STAGE       = var.osaka_stage
  }
}

module "dr_apigw_enable" {         # 東京を開放する
  image_config_command = ["dr_switch.apigateway.handlers.enable"]
  environment = {
    REGION         = "ap-northeast-1"
    REST_API_ID    = aws_api_gateway_rest_api.this.id
    STAGE          = aws_api_gateway_stage.this.stage_name
    THROTTLE_RATE  = 10000
    THROTTLE_BURST = 5000
  }
}

module "dr_nlb_check" {            # 東京を確認する
  image_config_command = ["dr_switch.nlb.handlers.check"]
  environment = {
    REGION             = "ap-northeast-1"
    TARGET_GROUP_ARNS  = jsonencode(var.target_group_arns)
    LOAD_BALANCER_ARNS = jsonencode(var.load_balancer_arns)
  }
}
```

`REGION` は全関数で必須。他は使う関数にだけ渡す。設定クラスごとの必須項目は
`REST_API_ID` / `STAGE`（ApiGateway 系すべて）、`THROTTLE_RATE` / `THROTTLE_BURST`
（`ApiGatewayEnableConfig` / `ApiGatewayCheckConfig` のみ）、`SCHEDULE_GROUP`
（Scheduler 系すべて）、`EKS_CLUSTERS`（各要素は `name` と `namespaces` が必須）。

## Step Functions への組み込み

```json
"FenceApiGw": {
  "Type": "Task",
  "Resource": "arn:aws:states:::lambda:invoke",
  "Parameters": {
    "FunctionName": "dr-apigateway-block",
    "Payload": {"dry_run.$": "$.dry_run"}
  },
  "Retry": [{
    "ErrorEquals": ["RetryableError", "Lambda.ServiceException",
                    "Lambda.TooManyRequestsException"],
    "IntervalSeconds": 5, "MaxAttempts": 3, "BackoffRate": 2
  }],
  "Catch": [{
    "ErrorEquals": ["ContinuableError"],
    "ResultPath": "$.fenceApiGwError",
    "Next": "FenceScheduler"
  }],
  "Next": "FenceScheduler"
}
```

観測系は `Retry` の間隔を長くするだけでよい。**`Wait` + `Choice` の待機
ループは不要**。`MaxAttempts` がそのまま待機上限になる。

```json
"CheckNlb": {
  "Type": "Task",
  "Resource": "arn:aws:states:::lambda:invoke",
  "Parameters": {"FunctionName": "dr-check-nlb"},
  "Retry": [{
    "ErrorEquals": ["RetryableError"],
    "IntervalSeconds": 30, "BackoffRate": 1.0, "MaxAttempts": 10
  }],
  "End": true
}
```

- 同じ例外名でも、ステートごとに間隔と回数を別々に指定できる
- 閉塞（role=peer）の失敗は `ResultPath` に記録して続行。リソース単位に
  分かれているので、どれが閉塞できなかったかが実行履歴からそのまま分かる
- 観測系 9 本は `Parallel` で並列実行する。どれか 1 つでも
  `RetryableError` で失敗すれば Parallel 全体が失敗する

## ループを Lambda 内で回す理由（Map を使わない）

Step Functions の Map で 1 バケット / 1 スケジュールずつ呼び分ける案は採らない。

- **Inline Map** は部分失敗を許容できない（`ToleratedFailureCount` /
  `ToleratedFailurePercentage` は Distributed Map の機能）。1 件失敗した時点で
  Map 全体が失敗するため、現在の「残りを試みて集約」が再現できず改悪になる
- **Distributed Map** なら `ToleratedFailurePercentage: 100` で同じ挙動を宣言
  でき、失敗した項目だけの redrive も使える。ただし子ワークフロー実行が項目数
  ぶん発生し、ResultWriter を使うなら両リージョンに S3 バケットが必要で、
  項目リストの置き場所が環境変数から ASL 側へ分散する
- 対象がバケット数個・スケジュール数個という規模では構成が重すぎる。得られる
  のは実質 redrive だけで、操作が冪等な今回はワークフロー再実行で代替できる

## フェーズ順序

```
Fence(peer): apigw -> scheduler          # ContinuableError を Catch して続行
  [案 A のみ] s3-replication(self, enabled=true)
  [案 A のみ] s3-replication(peer,  enabled=false)   # 失敗許容
Check(self): apigw / lambda / dynamodb / nlb / s3 / alarms / workload  # 並列
Activate(self): scheduler -> apigw       # 失敗は未捕捉 = 停止
```

案 A の `role=self` 有効化は **必ず Activate より前**。ライブレプリケーション
の対象は「ルールが Enabled になった後に書かれたオブジェクト」だけなので、
開放が先だと取りこぼしが発生し、Batch Replication での追い付きが必要になる。

## API Gateway の閉塞方式

**ステージのスロットリングを 0 にする方式**を採る。

    閉塞: rateLimit=0 / burstLimit=0  -> 全リクエストが 429
    開放: 環境変数（または引数）の値に戻す

復元値は `THROTTLE_RATE` / `THROTTLE_BURST`（既定 10000 / 5000）。既定値は
現在ステージに設定されている値と同じなので、開放は元の状態への復元になる。
Step Functions から `{"throttle": {"rate": ..., "burst": ...}}` で上書きできる。

なお `op:remove` は非サポートのため、`replace` で値を書き換えることしかできない。

### check が確認するもの

| 項目 | API | 判定 |
|---|---|---|
| API の状態 | `get_rest_api` の `apiStatus` | `AVAILABLE` / `UPDATING` は正常 |
| スロットリング値 | `get_stage` の `methodSettings["*/*"]` | 環境変数の値と一致するか |

`apiStatus` の取り得る値は `AVAILABLE` / `UPDATING` / `PENDING` / `FAILED`。
**公式が意味を説明しているのは 1 つだけ**で、「ステータスメッセージが `UPDATING`
のときも呼び出しは可能」と記載がある。`PENDING` / `FAILED` の意味を説明した
記述は公式・コミュニティとも見つからず、名称からの判断で `PENDING` を
`RetryableError`、`FAILED` を `NotRecoverableError` に振り分けている。

### ステータス値の扱い

boto3 は **AWS の SDK の中で例外的に enum を Python の定数として提供しない**。
JSON のサービスモデルから実行時にクライアントを組み立てる設計のため、
レスポンスは素の dict、enum は素の文字列になる（Go / Kotlin / Java の SDK には
型付き enum がある）。したがって boto3 では文字列比較が標準的な書き方になる。

そのうえで、扱う定数には性質の違う 2 種類がある。

| 種類 | 例 | AWS から取れるか |
|---|---|---|
| 値の集合 | `ApiStatus` の取り得る値 | **取れる**。二重定義は避ける |
| 値の分類 | どの値が「正常」「待てば直る」か | **取れない**。業務判断なので書くしかない |

**値の集合には `boto3-stubs` の `Literal` を使う。** 実行時には不要なので
`if TYPE_CHECKING:` の中で import する。型チェッカが「enum に無い値を書いた」を
検出できる。

```python
if TYPE_CHECKING:
    from mypy_boto3_lambda.literals import StateType

HEALTHY_STATES: frozenset[StateType] = frozenset({"Active"})
```

**分類は enum の全値を明示する。** 未分類の値が出ないよう、`HEALTHY` /
`TRANSIENT` / `FATAL` の 3 集合で全値を覆う。boto3 を更新して AWS が値を
追加した場合、実装は未知の値を「待っても解消しない」側に倒す（保守的な既定）。

| 対象 | enum | 分類済み |
|---|---|---|
| apigateway | `ApiStatus` | 4 値 |
| lambda | `State` | 8 値 |
| lambda | `LastUpdateStatus` | 3 値 |
| dynamodb | `TableStatus` | 8 値 |
| nlb | `TargetHealthStateEnum` | 7 値 |
| scheduler | `ScheduleState` | 2 値 |
| s3 | `ReplicationRuleStatus` | 2 値 |
| cloudwatch | `StateValue` | ALARM のみ取得対象 |

EKS のワークロード確認は Kubernetes API を使うため、この仕組みの対象外。
`kubernetes` パッケージは同様の Literal を提供しない。

### boto3 のバージョン要件

`apiStatus` は **botocore 1.41.0 でモデルに追加された**フィールド。
boto3/botocore はサービスの応答を自分が持つ API モデルに従ってパースするため、
**モデルに無いフィールドはサービスが返していても捨てられる**。

実測（1.40.x と 1.41.0 でパース結果を比較）で確認済み。

| boto3 | botocore | `apiStatus` |
|---|---|---|
| 1.40.11 | 1.40.76 | **落とされる** |
| 1.41.0 | 1.41.6 | 取得できる |
| 1.43.72（最新） | 1.43.72 | 取得できる |

`requirements.txt` は **`boto3==1.43.72`**（執筆時点の最新）を指定している。
**1.41.0 未満に下げると、`apigateway` の check の状態確認が黙ってスキップされる**
（フィールドが無い場合は異常として扱わない実装のため、失敗にもならない）。

古いバージョンに固定する利点は無い。新しいサービスフィールドが取れなくなる
だけで、今回の問題がまさにそれだった。

なお開発環境の AWS CLI 2.30.4 は botocore 1.40.x 相当で、`get-rest-api` の
出力に `apiStatus` が現れない。サービスは返しているので、`--debug` で
Response body を見れば確認できる。

### HTTP リクエストを投げない理由

切替で変更するのはステージのスロットリングだけで、これはステージ設定のため
再デプロイを伴わない。設定が反映されたことは `get_stage` で確認できる。

統合先まで含めた到達性を確認するには副作用の無いエンドポイント（Mock 統合の
`/health` など）が必要になるが、既存 API に副作用の無い参照系が無いため
用意していない。切替後に実際にトラフィックが流れたかは、CloudWatch の
`Count` / `5XXError` メトリクスで追跡する。

### リソースポリシー Deny 方式を採らない理由

1. リソースポリシーの更新は再デプロイしないと反映されず 2 手になる
2. `/policy` への patch は `op:replace` のみ（`op:add` / `op:remove` は
   非サポート）で、Statement 単位の更新ができない。既存ポリシーに IP 制限等が
   あると閉塞のたびに壊す危険がある
3. 旧アクティブ側の閉塞はリージョン障害中に実行できない可能性があり、構造的に
   ベストエフォート。遮断機構だけを「保証された」ものにする必然性がない

スロットリングは公式に「ベストエフォートで適用され、保証された上限ではなく
目標値」とされている。理論上わずかな漏れの可能性は残るが、3 の理由から許容する。

### Terraform で管理しない理由

`aws_api_gateway_method_settings` で管理することもできるが、Lambda が値を
書き換えるためドリフト対策（`ignore_changes`）が必要になる。管理コストが
増えるだけで得るものがないため、復元値は Lambda の環境変数だけで持つ。

## S3 レプリケーション: 案 A / 案 B

未確定のため両方に対応できる形にしてある。

### 案 A（切替時に Status をトグル）

平時は逆方向ルールを `Disabled` にしておき、切替時に `dr-s3-replication`
で Status を書き換える。

Terraform との整合: 現行モジュールは `var.run_replication` で `status` を
制御しているため、Lambda が書き換えるとドリフトする。次のいずれかが必要。

- `lifecycle { ignore_changes = [rule] }` を付けて Status を Terraform 管理外にする
- 切替を恒久化する際に tfvars の `run_replication` も合わせて更新する運用にする

案 A 固有のリスク: `PutBucketReplication` は宛先バケットの存在を検証する。
相手リージョンが全域障害の最中にこの検証が通るかは公式に明記がなく確定
できない。切替のクリティカルパスにこの不確実性を抱える点が弱点。

### 案 B（双方向を常時 Enabled）

`dr-s3-replication` はデプロイしない。切替時の S3 操作はゼロになる。
tfvars で両リージョンとも `run_replication = true` に固定する。
`dr-check-s3` は「意図せず Disabled になっていないか」の確認として機能する。

### 両案共通

`aws_s3_bucket_replication_configuration` の rule に `metrics` を有効化して
おくこと。切替可否のゲートには使わないが、切替後の突合と平時の RPO 可視化に
必要。東京 -> 大阪ルールの PENDING は宛先である大阪の CloudWatch に出るため、
東京障害中でも大阪側から取り残し量を読める。

`delete_marker_replication` は `Disabled` のまま。仕様上オブジェクト削除が
ないため `Enabled` にする利点がなく、誤削除が両リージョンへ波及するリスク
だけが残る。誤削除時に切替先へコピーが残ることが保護になる。

## EventBridge Scheduler の確認内容

| 対象 | API | 判定 |
|---|---|---|
| グループの状態 | `get_schedule_group` の `State` | `ACTIVE` が正常。`DELETING` は `NotRecoverableError` |
| スケジュールの State | `list_schedules` の `Schedules[].State` | すべて `ENABLED` |

`ScheduleGroupState` は `ACTIVE` / `DELETING` の 2 値。`DELETING` はグループの
削除処理中で、そのグループのスケジュールは動かない。待っても `ACTIVE` には
戻らないため `NotRecoverableError` に振り分ける。切替ワークフローが操作しない
値なので、`DynamoDB` の `TableStatus` と同じ位置づけ。

スケジュールの `State` は切替で操作した値そのものなので、`apigateway` が
スロットリング値を確認しているのと同じ「反映確認」にあたる。

## EventBridge Scheduler

イベント駆動は EventBridge **Rules ではなく Scheduler**（スケジュール）を
使っている。`events` ではなく `scheduler` クライアントを叩く。

自チーム専用のスケジュールグループが独立して存在するため、
`SCHEDULE_GROUP` にそのグループ名を指定すればグループ内全件が対象になる。
default グループの他チーム分には触れない。

### UpdateSchedule の注意点

State だけを渡す API は存在しない。`UpdateSchedule` は必須パラメータを
すべて要求し、渡した内容でスケジュールを丸ごと置き換える。指定しなかった
パラメータは null になる。そのため必ず

    get_schedule -> 読み取り専用フィールドを除去 -> State を差し替え -> update_schedule

の順で行う。S3 の `put_bucket_replication` と同じ構造。
除去する読み取り専用フィールドは
`ResponseMetadata` / `Arn` / `CreationDate` / `LastModificationDate`。

冪等判定は `list_schedules` の戻り値に含まれる `State` で行うため、
変更不要なものに `get_schedule` は発行しない。

## NLB の確認内容

| 対象 | API | 判定 |
|---|---|---|
| ロードバランサ自体 | `describe_load_balancers` の `State.Code` | `active` が正常 |
| 登録済みターゲット | `describe_target_health` の `TargetHealth.State` | unhealthy 系 0 かつ 遷移中 0 かつ healthy >= 1 |

`State.Code` の意味は公式に記載がある。初期状態が `provisioning`、
セットアップ完了で `active`、ルーティングはできるがスケールに必要なリソースが
不足していると `active_impaired`、セットアップに失敗すると `failed`。

`active_impaired` はトラフィックを流せるが不安定なので待てば直る側、
`failed` は `NotRecoverableError` に振り分ける。

`LOAD_BALANCER_ARNS` が未設定なら、ロードバランサ自体の確認はスキップする。

## NLB の構成と判定の意味

NLB とターゲットグループは AWS Load Balancer Controller が Service から作成。
**ターゲットタイプは IP**、トラフィック・ヘルスチェックとも **TCP** で、
`HealthCheckPort` は `traffic-port`。ターゲットグループは 2 つ（Port 1 / 9116）。

IP モードでは NLB が Pod IP へ直接トラフィックを送るため、トラフィックは
kube-proxy を経由せず、`externalTrafficPolicy` は判定に関係しない。
Controller は Endpoints / EndpointSlices からターゲットを解決し、一覧に無い
ターゲットは即座に登録解除する。したがって

    登録されているターゲット ≒ Ready な Pod

`dr-check-nlb` は「登録済みのターゲットがすべて健全か」だけを見る。

    unhealthy == 0  かつ  initial == 0  かつ  healthy >= 1

必要数を満たしているかの判定は `dr-check-workload` に一本化している。
`initial` を許容しないのは、EndpointSlice の更新が ELB のターゲット登録より
速く進むため、早すぎる開放を防ぐ必要があるから。

Hybrid Node の Ready 状態や Pending 状態の Pod はターゲットグループに
現れないため、`dr-check-workload` との併用が前提。

## Pod の再起動

既存の Pod 再起動 Lambda を**並列に**呼び出す。対象クラスタ・namespace・Pod は
**呼ばれる側が保持している**ため、こちらは関数名のリストを持つだけ
（`POD_RESTART_FUNCTIONS`）。

```python
# aws lambda invoke --function-name <name> --invocation-type RequestResponse
#   の StatusCode / FunctionError
```

### 並列に呼ぶ理由

呼ばれる側は **Pod の起動完了を待つ**実装のため、逐次だと本数ぶん時間が
積み上がる。順序依存が無いので `ThreadPoolExecutor` で全件同時に投げる。
boto3 のクライアントはスレッドセーフなので共有してよい。

### 失敗の扱い

**全件を投げてから結果を集める。** 途中で失敗しても他は既に走っているので
中断はできない。失敗が 1 件でもあれば `NotRecoverableError` を送出し、
どの関数が失敗したかをすべて載せる。

`FunctionError` が返る場合は呼ばれた側が例外で終了している。応答本文の
先頭 500 文字を記録する。

### タイムアウト

`BOTO_CONFIG` の `read_timeout=10` 秒では呼ばれる側の実行時間に足りない。
`POD_RESTART_TIMEOUT`（既定 300 秒）で設定し、**呼ばれる側の Lambda の
Timeout に合わせる**。この関数自体の Lambda タイムアウトも、それを上回る
値にする必要がある。

リトライは行わない（`max_attempts=0`）。呼ばれる側が冪等とは限らないため、
同じ再起動が二重に走るのを避ける。

### 収束の確認は check が担当する

`restart_pods` が見るのは呼び出しが成功したことまで。再起動後に Pod が
Ready になったかは `eks` の check（`readyReplicas >= spec.replicas`）で
確認する。フェーズ順序は restart_pods を先、check を後にする。

## Pod 再起動の 2 方式

用途に応じて選ぶ。**どちらか一方だけをデプロイする**想定。

| | `restart_pods` | `rollout_restart` |
|---|---|---|
| 手段 | 既存の Pod 再起動 Lambda を `Invoke` | Kubernetes API を直接 patch |
| 対象の指定 | 呼ばれる側が保持 | `restart_targets` に `kind` と `name` で明示 |
| 完了待ち | **待つ**（呼ばれる側の実装） | 待たない |
| 所要時間 | 呼ばれる側次第（並列化して短縮） | patch のみで即完了 |
| 必要な権限 | `lambda:InvokeFunction` | Kubernetes RBAC の `patch` |

### rollout_restart の中身

`kubectl rollout restart deployment -n <ns>` 相当。kubectl はテンプレートの
annotations に `kubectl.kubernetes.io/restartedAt` を書き込むだけで、実際の
Pod 入れ替えはコントローラが行う。ここでも同じ patch を送る。

```python
{"spec": {"template": {"metadata": {"annotations": {
    "kubectl.kubernetes.io/restartedAt": "<RFC3339>"}}}}}
```

**完了は待たない。** 収束は check（`readyReplicas >= spec.replicas`）が確認する。
待機を Lambda ではなく Step Functions の `Retry` に任せるので、実行履歴に
待機が残り、Lambda のタイムアウトにも縛られない。

対象は `NamespaceConfig.restart_targets` に `kind` と `name` で明示する。
空なら何もしない（その namespace は check の対象にはなる）。対象が 1 つも
無いクラスタは kubeconfig の生成もスキップする。

`kind` に指定できるのは `Deployment` と `DaemonSet`。**DaemonSet は Hybrid Node
上で vLB からの受信を担うため、再起動すると切替中の取りこぼしにつながりうる。**
含めるかは要判断。

`check` は Kubernetes RBAC の `list` で足りるが、`rollout_restart` は
`deployments` / `daemonsets` への **`patch` が必要**。

## EFS の確認内容

EKS の Pod が EFS CSI ドライバ経由で利用する。

| 対象 | API | 判定 |
|---|---|---|
| ファイルシステム | `describe_file_systems` の `LifeCycleState` | `available` が正常 |
| マウントターゲット | `describe_mount_targets` の `LifeCycleState` | `available` が正常 |

`LifeCycleState` は `creating` / `available` / `updating` / `deleting` /
`deleted` / `error` の 6 値。`creating` / `updating` は待てば変わるので
`RetryableError`、それ以外は `NotRecoverableError`。

### eks の check と重複しない理由

**既にマウント済みの Pod は NFS マウントを保持し続ける。** マウントターゲットが
`error` になっても Pod は動き続けるため、`eks` の check は `ready == want` で
正常と判定する。切替後に Pod が再起動すると、そこで初めてマウントに失敗する。

Lambda の `Inactive` と同じく「必要になるまで気づけない」性質なので、独立して
確認する。

### アクセスポイントを確認しない理由

EFS CSI ドライバの動的プロビジョニングでは PVC の増減に応じてアクセスポイントが
作られる。使われていない古いものを拾って誤検知しうるため対象にしない。

## 存在確認は行わない

**確認対象は「時間経過で失われうる状態」に限る。** リソースが存在するかどうかは
切替時に確認しない。存在しないなら Terraform の適用漏れであり、切替時に気づいても
その場では直せない。

そのうえで、`GetQueueAttributes` や `HeadBucket` のような呼び出しが成功しても、
それは**コントロールプレーンが応答したことしか示さない**。AWS は
コントロールプレーンとデータプレーンを明確に分けており、「プロビジョニング済みの
リソースへのデータプレーンアクセスはコントロールプレーンに依存しない」と
明記している。つまり存在確認が通ってもメッセージ送受信やオブジェクト読み書きが
できる保証にはならず、逆にコントロールプレーン障害で通らなくても
データプレーンは動いている可能性がある。

Well-Architected は「**復旧時にはコントロールプレーンではなくデータプレーンに
依存せよ**」をリスクレベル「高」で示している。

### SQS を確認対象から外す理由

**SQS の API には状態を表す属性が存在しない。** `GetQueueAttributes` が返す
22 の属性はいずれも設定値と概算メッセージ数で、キューの健全性を示すものが無い
（API モデルで確認済み。状態を表すシェイプも存在しない）。確認する対象そのものが
無いため、ハンドラを用意しない。

滞留件数（`ApproximateNumberOfMessages`）も見ない。DLQ の滞留は過去の処理失敗の
痕跡で、切替先でサービスを開始できるかとは別。切替後に CloudWatch メトリクスで
追跡する。

### S3 のバケット存在確認を行わない理由

バケットには状態という概念が無く、時間経過で失われる性質のものでもない。
`s3` の check はレプリケーションルールの `Status` だけを見る。これは
「案 A で自分が変更した設定が反映されたか」の確認であり、`apigateway` が
スロットリング値を見ているのと同じ性質。

## EKS ワークロードの判定

### 対象

自チームのクラスタは 2 つあり、namespace は両クラスタで同じ。別 namespace には
他チームの Pod も乗っているため、namespace で絞る。ワークロードは
Deployment / DaemonSet / CronJob の 3 種。

設定はクラスタ単位の入れ子にする。クラスタごとに namespace が違い得るため、
クラスタと並列には置けない。

```hcl
EKS_CLUSTERS = jsonencode([
  {
    name = "cluster-a"
    namespaces = [
      {
        name = "ns-1"
        # rollout restart の対象。空または未指定なら再起動しない
        restart_targets = [
          { kind = "Deployment", name = "app-a" },
          { kind = "Deployment", name = "app-b" },
        ]
      },
      { name = "ns-2" },
    ]
  },
  {
    name       = "cluster-b"
    namespaces = [{ name = "ns-1" }]
  },
])
```

`namespaces` はオブジェクトの配列。`check` は `name` だけを見て namespace 配下を
全件確認し、`rollout_restart` は `restart_targets` に列挙されたものだけを
再起動する。**確認対象と再起動対象は範囲が違う**ため、同じ階層に別々の項目として
持たせる。

`namespaces` は必須。全チーム共通の Lambda に包含する場合も、クラスタを
足すか namespaces に全チーム分を列挙すればよい。

### 種別ごとの判定条件

| 種別 | 必要数の出どころ | 判定 |
|---|---|---|
| Deployment | `spec.replicas` | `status.readyReplicas >= spec.replicas` |
| DaemonSet | **ノード数から算出** | `numberReady >= desiredNumberScheduled` かつ `numberMisscheduled == 0` かつ **`desiredNumberScheduled > 0`** |
| CronJob | — | **確認しない**（下記） |

**DaemonSet の `desiredNumberScheduled` は Pod 数ではなくノード数由来**で、
セレクタに一致するノードが 0 台なら 0 になる。すると `numberReady(0) ==
desired(0)` が成立し、Pod が 1 つも無いのに正常と判定される。自チームの
DaemonSet は Hybrid Node 上のみで動くため、Direct Connect 断でこれが実際に
起こり得る。`desiredNumberScheduled == 0` は異常として扱う。

**CronJob は確認対象から外す。** Pod は Job 実行中しか存在せず readiness の
概念が無い。確認できるのは `spec.suspend` だが、Kubernetes がこれを自動で
立てることはなく、切替ワークフローも触らないため、検出できるのは平時の
構成ドリフトだけになる。`spec.replicas` のドリフトを切替時に見ないと決めたのと
同じ理由で外す（`lastScheduleTime` は切替直後は定義上古いので使えない）。

### ノードを確認しない理由

Hybrid Node の Ready を直接確認する案は採らない。DaemonSet の判定と
検出できる事象が重なり、ノード確認だけが検出できる事象が無いため。

| 事象 | ノード確認 | DaemonSet 確認 |
|---|---|---|
| ノードがクラスタから消えた | セレクタ一致 0 台 | `desired == 0` |
| ノードは居るが NotReady | `Ready != True` | `ready < desired` |
| ノードは Ready だが Pod が落ちている | 検出不可 | `ready < desired` |

固有の価値はノード名が分かることだけで、切替可否の判断は変わらない。
一方 Node はクラスタスコープのリソースなので ClusterRoleBinding が必要になる。
得るものに対して権限の範囲が広がりすぎる。

この判断により、必要な RBAC は namespaced リソースの読み取りだけになる
（各 namespace の RoleBinding のみ。ClusterRoleBinding は不要）。

### Pending Pod の扱い

CronJob が作る Job Pod は起動直後に Pending になるのが正常なため、
`ownerReferences` が Job のものは除外する。

### CronJob を閉塞対象に含めない理由

入口（vLB）が閉塞されれば処理対象のファイルが増えなくなり、空振りするだけの
ため。むしろ動かし続けることで、閉塞直前に書き込まれた未処理ファイルを
S3 へ吐き出して回収できる。

## dr.eks の接続方式

既存の Pod 再起動 Lambda と同じ方式（`aws eks update-kubeconfig`）を使う。

- CA 証明書とトークン取得は CLI が肩代わりするため、Python 側の実装は不要
  （kubeconfig の exec プラグインが `aws eks get-token` を都度実行する）
- クラスタ API エンドポイントはプライベートのみのため、到達可能な
  VPC・サブネット・セキュリティグループに配置する（既存 Lambda と同じ設定）
- 実行ロールを EKS アクセスエントリで view 相当にマッピングする

## タイムアウトと所要時間の試算

応答しない相手を待ち続けて RTO を消費しないよう、外部と通信するすべての
呼び出しにタイムアウトを設定している。

| 呼び出し | 設定 | 場所 |
|---|---|---|
| AWS API（boto3） | connect 5 秒 / read 10 秒、リトライは standard モードの既定（合計 3 試行） | `dr_switch.core.aws.BOTO_CONFIG` |
| Kubernetes API | connect 3 秒 / read 10 秒 | `dr_switch.eks.handlers.K8S_TIMEOUT` |
| `aws eks update-kubeconfig` | 15 秒 | `dr_switch.eks.handlers.UPDATE_KUBECONFIG_TIMEOUT_SEC` |
| ヘルスチェックの HTTPS | 5 秒 | `dr_switch.apigateway.handlers.HEALTH_TIMEOUT_SEC` |

`read_timeout` を 10 秒にしているのは、呼ぶのが describe / update 系の
コントロールプレーン API で通常 0.3 秒程度のため。30 倍の余裕があり、
**正常な呼び出しを打ち切ることはない**（短くしすぎると、成功するはずの
呼び出しが打ち切られて 3 回リトライされ、かえって遅くなる）。

### リトライは 2 層

| 層 | 対象 | 時間スケール |
|---|---|---|
| SDK（botocore standard モード） | 個々の API 呼び出し | 一過性で約 75ms、スロットリングで約 1.5 秒 |
| Step Functions（`RETRYABLE_CODES` 経由） | Lambda 全体 | 5〜30 秒間隔 |

**SDK のリトライ回数は既定（合計 3 回）のまま使う。** AWS は standard モードを
推奨し既定を 3 回としており、バックオフが短いため RTO への影響は無視できる。
回数を削ると、本来 SDK が吸収できる失敗が呼び出し元まで漏れる。
`mode` だけ明示するのは、boto3 の既定がまだ非推奨の `legacy` のため。

**注意**: `max_attempts` は設定場所で意味が変わる。`Config(retries=...)` では
リトライ回数（合計 N+1 回）、環境変数 `AWS_MAX_ATTEMPTS` では合計試行回数
（1 でリトライ無効）。

### ハンドラごとの所要時間

障害の現れ方で分けて試算する。

- **到達不能** … TCP 接続が張れない。DR で想定する主な状態。`connect_timeout × 3 = 15 秒 / 呼び出し`
- **ハング** … 接続はできるが応答が返らない。まれ。`(connect + read) × 3 = 45 秒 / 呼び出し`

リソース数の実績値: スケジュール 1 / バケット 1 / 関数 16 / テーブル 3 /
namespace 1 / クラスタ 2 / ターゲットグループ 2。

| ハンドラ | 呼出数 | 通常 | 到達不能 | ハング |
|---|---|---|---|---|
| apigateway.block / enable | 2 | 0.6s | 15s | 90s |
| apigateway.check | 2 | 0.6s | 20s | 50s |
| scheduler.block / enable | 3 | 0.9s | 15s | 135s |
| s3.block / enable / check | 2 | 0.6s | 15s | 90s |
| lambda_function.check | 16 | 4.8s | 15s | 720s |
| dynamodb.check | 3 | 0.9s | 15s | 135s |
| nlb.check | 2 | 0.6s | 15s | 90s |
| cloudwatch.check | 1 | 0.3s | 15s | 45s |
| eks.check | 8 | 4.8s | 15s | 54s |

**Lambda のタイムアウトは全ハンドラ 60 秒**。到達不能の最大 20 秒 ＋ 通常の
最大 5.1 秒 ＋ 余裕。AWS が示す式
（初回 + リトライ回数 ×（connect + read）+ 20 秒の余裕）でも
`(5+10)×3+20 = 65 秒` とほぼ一致する。

ハングした場合は 60 秒で打ち切られ、Step Functions が失敗として扱う。
765 秒待つことはない。

**閉塞フェーズは旧リージョンが落ちていても 45 秒で完了する**
（apigateway 15 + scheduler 15 + s3 15）。

### lambda_function.check が見るもの

**関数の `State` / `LastUpdateStatus` だけ**を確認する。

VPC 設定のある関数は、長くアイドル状態が続くと Lambda が外部リソースを回収し
`State` が `Inactive` になる。公式に「非アクティブな関数を呼び出すと**呼び出しは
失敗し**、リソースが再作成されるまで Pending になる」と記載がある。待機側の関数は
普段呼ばれないため、**切替の瞬間にこの状態になっている可能性がある**。
Lambda が自動で遷移させ、実害が出る点で、確認する価値が明確にある。

`GetFunction`（デプロイパッケージの URL 付き）ではなく
`GetFunctionConfiguration` を使う。IAM も狭い権限で済む。

`ListFunctions` で 1 回にまとめることはできない。公式に「ListFunctions は
FunctionConfiguration のサブセットを返す。State 等を得るには GetFunction を
使う」と明記されている。関数数ぶんの呼び出しは避けられない。

### イベントソースマッピングを確認しない理由

ESM の State は `Creating` / `Enabling` / `Enabled` / `Disabling` / `Disabled` /
`Updating` / `Deleting` だが、**Lambda が自動で `Disabled` にするという記述は
無い**。`Disabled` になるのは明示的な操作の結果で、切替ワークフローも触らない。

遷移中の状態（`Creating` / `Enabling` / `Updating`）は収束待ちとして正当だが、
待機側は前から動いているため、切替直前にデプロイした場合しか観測されない。

結局、構成ドリフトしか検出できない。`spec.replicas` のドリフトを見ないと決め、
CronJob の `suspend` を外したのと同じ基準で確認対象から外す。

### 接続系エラーでのループ中断

`run_per_item` は接続系エラー（`TRANSIENT_ERRORS`）のときだけ中断する。
エンドポイントに到達できない状態は項目に依存しないので、残りを試しても
同じ結果になり、項目数ぶんタイムアウトを積み上げるだけになるため。
項目ごとのエラー（権限不足など）は従来どおり全件試行して集約する。

## dry_run

変更系 6 本は `{"dry_run": true}` で読み取りと「実行予定の操作」の返却のみ
行う。EventBridge Scheduler で週次実行すれば、IAM 権限不足や設定漏れを平時に
検出できる（訓練時にしか動かないコードの潜伏対策）。特に `dr-scheduler` の
`iam:PassRole` は見落としやすいので、ここで早期に検証する。

## 制御設計についての判断

| 論点 | 判断 |
|---|---|
| 「未収束」を例外（`RetryableError`）で表現する | **現状維持**。AWS のポーリング定型は `Wait` + `Choice` であり意味論の批判は成立するが、実務上の差はなく ASL が単純になる利点が上回る |
| 閉塞失敗時に無条件で続行する | **現状維持**（下記） |
| 正常性確認が実機能を検証していない | **制約として受容**。NE 機器への誤警報になるため真のエンドツーエンド試験ができない。切替後の流量メトリクスの立ち上がりで代替する |
| ワークフロー全体のタイムアウト・二重実行防止 | Step Functions 側の作業。ASL 着手時の要件とする |

### 閉塞失敗時の扱い（現状維持と決定）

閉塞に失敗しても切替を続行する。理由は、閉塞が失敗する主要因が旧リージョンの
障害そのものであり、その場合は旧リージョン側のサービスも動いていないため。

残るのは「部分障害で旧リージョンのアプリは生きているが、閉塞だけ失敗した」
ケースで、理論上は両リージョンが同時にアクティブになりうる。ただし
**判定手段がない**ため、対処を入れないと決めた。

判定手段がない根拠:

- 新 ACTIVE 側から旧リージョンを 1 回叩く方式は単一拠点からの判定になり、
  リージョン間のネットワーク分断を「旧リージョンの停止」と誤判定する。
  Route 53 が 18% という合議しきい値を持つのは、まさにこの誤判定
  （ネットワーク条件による一部拠点からの隔離）を避けるため
- 多拠点合議で判定するなら Route 53 ヘルスチェックを新設し、CloudWatch
  （us-east-1）の `HealthCheckStatus` を読む必要がある。DR 専用のリソース
  追加は避ける方針のため採らない
- ARC のルーティングコントロールは「人間やランブックをフェイルオーバーの
  ループに入れたい場合の正解」とされる明示的なスイッチであり、AWS 自身も
  自動推論ではなく人間の判断を前提にしている

閉塞失敗は `ContinuableError` として実行履歴の `ResultPath` に残るため、
事後に「どのリソースが閉塞できなかったか」は追跡できる。

## 残っている作業

| 項目 | 内容 |
|---|---|
| F-10 | Dockerfile の分割。AWS CLI が必要なのは `dr_switch.eks` のみだが、10 本すべてのイメージに入っている |
| F-11 | boto3 のバージョン固定。現在はランタイム同梱を使っている |
| F-19 | ユニットテスト未作成 |
| — | Step Functions の ASL 本体（フェーズ構成、Parallel、Retry / Catch の配線、全体タイムアウト、二重実行防止） |
| — | Terraform 側の関数定義（`image_config.command` でハンドラを切り替える 10 本分） |
| — | S3 レプリケーションの案 A / 案 B の決定 |
