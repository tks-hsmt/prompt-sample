# ============================================================================
# DR 切替 Lambda の定義（唯一の追加・変更箇所）
#
# 関数を増やすときは local.functions にエントリを 1 つ足すだけでよい。
# ロール・ポリシー・関数定義は iam.tf / lambda.tf の for_each が生成するので、
# resource 側に手を入れる必要はない。
#
# 各エントリの構造
#
#   handler   … コンテナイメージの image_config.command に渡すハンドラ
#   env       … 環境変数。REGION は必須
#   policy    … IAM ポリシーのステートメント配列
#                 actions            必須
#                 resources          必須
#                 pass_role_service  任意。iam:PassRole の渡し先を限定する
#   vpc       … 任意。既定 true（全関数を VPC 内に配置する方針）
#   timeout   … 任意。既定 local.default_timeout
# ============================================================================

locals {
  # 到達不能時 15〜20 秒 ＋ 通常の最大 5 秒 ＋ 余裕
  default_timeout = 60

  functions = {
    # --- API Gateway -------------------------------------------------------
    "apigateway-block" = {
      handler = "dr_switch.apigateway.handlers.block"
      env = {
        REGION      = var.peer_region
        REST_API_ID = var.peer_rest_api_id
        STAGE       = var.peer_stage
      }
      policy = [{
        actions   = ["apigateway:GET", "apigateway:PATCH"]
        resources = [local.peer_stage_arn]
      }]
    }

    "apigateway-enable" = {
      handler = "dr_switch.apigateway.handlers.enable"
      env = {
        REGION         = var.self_region
        REST_API_ID    = var.self_rest_api_id
        STAGE          = var.self_stage
        THROTTLE_RATE  = var.throttle_rate
        THROTTLE_BURST = var.throttle_burst
      }
      policy = [{
        actions   = ["apigateway:GET", "apigateway:PATCH"]
        resources = [local.self_stage_arn]
      }]
    }

    "apigateway-check" = {
      handler = "dr_switch.apigateway.handlers.check"
      env = {
        REGION         = var.self_region
        REST_API_ID    = var.self_rest_api_id
        STAGE          = var.self_stage
        THROTTLE_RATE  = var.throttle_rate
        THROTTLE_BURST = var.throttle_burst
      }
      # get-rest-api（apiStatus）と get-stage（スロットリング値）で対象が違う
      policy = [{
        actions   = ["apigateway:GET"]
        resources = [local.self_api_arn, local.self_stage_arn]
      }]
    }

    # --- EventBridge Scheduler ---------------------------------------------
    # UpdateSchedule は Target.RoleArn を含む全パラメータを要求するため
    # iam:PassRole が必須。他のどの関数にも不要な権限なので見落としやすい。
    "scheduler-block" = {
      handler = "dr_switch.scheduler.handlers.block"
      env     = { REGION = var.peer_region, SCHEDULE_GROUP = var.peer_schedule_group }
      policy = [
        {
          actions   = ["scheduler:ListSchedules", "scheduler:GetSchedule", "scheduler:UpdateSchedule"]
          resources = [local.peer_schedule_arn]
        },
        {
          actions           = ["iam:PassRole"]
          resources         = [var.peer_schedule_role_arn]
          pass_role_service = "scheduler.amazonaws.com"
        },
      ]
    }

    "scheduler-enable" = {
      handler = "dr_switch.scheduler.handlers.enable"
      env     = { REGION = var.self_region, SCHEDULE_GROUP = var.self_schedule_group }
      policy = [
        {
          actions   = ["scheduler:ListSchedules", "scheduler:GetSchedule", "scheduler:UpdateSchedule"]
          resources = [local.self_schedule_arn]
        },
        {
          actions           = ["iam:PassRole"]
          resources         = [var.self_schedule_role_arn]
          pass_role_service = "scheduler.amazonaws.com"
        },
      ]
    }

    "scheduler-check" = {
      handler = "dr_switch.scheduler.handlers.check"
      env     = { REGION = var.self_region, SCHEDULE_GROUP = var.self_schedule_group }
      policy = [
        {
          actions   = ["scheduler:GetScheduleGroup"]
          resources = [local.self_schedule_group_arn]
        },
        {
          actions   = ["scheduler:ListSchedules"]
          resources = [local.self_schedule_arn]
        },
      ]
    }

    # --- S3 ----------------------------------------------------------------
    # 案 A（切替時にトグル）を採る場合のみ block / enable をデプロイする。
    # バケットは SSE-S3（AES256）なので KMS 関連の権限は不要。
    "s3-block" = {
      handler = "dr_switch.s3.handlers.block"
      env = {
        REGION              = var.peer_region
        REPLICATION_BUCKETS = jsonencode(var.peer_replication_buckets)
      }
      policy = [
        {
          actions   = ["s3:GetReplicationConfiguration", "s3:PutReplicationConfiguration"]
          resources = local.peer_bucket_arns
        },
        {
          actions           = ["iam:PassRole"]
          resources         = [var.peer_replication_role_arn]
          pass_role_service = "s3.amazonaws.com"
        },
      ]
    }

    "s3-enable" = {
      handler = "dr_switch.s3.handlers.enable"
      env = {
        REGION              = var.self_region
        REPLICATION_BUCKETS = jsonencode(var.self_replication_buckets)
      }
      policy = [
        {
          actions   = ["s3:GetReplicationConfiguration", "s3:PutReplicationConfiguration"]
          resources = local.self_bucket_arns
        },
        {
          actions           = ["iam:PassRole"]
          resources         = [var.self_replication_role_arn]
          pass_role_service = "s3.amazonaws.com"
        },
      ]
    }

    "s3-check" = {
      handler = "dr_switch.s3.handlers.check"
      env = {
        REGION              = var.self_region
        REPLICATION_BUCKETS = jsonencode(var.self_replication_buckets)
      }
      policy = [{
        actions   = ["s3:GetReplicationConfiguration"]
        resources = local.self_bucket_arns
      }]
    }

    # --- Lambda / DynamoDB -------------------------------------------------
    "lambda-check" = {
      handler = "dr_switch.lambda_function.handlers.check"
      env = {
        REGION         = var.self_region
        FUNCTION_NAMES = jsonencode(var.self_function_names)
      }
      # GetFunction ではなく GetFunctionConfiguration。応答が軽く権限も狭い
      policy = [{
        actions   = ["lambda:GetFunctionConfiguration"]
        resources = local.self_function_arns
      }]
    }

    "dynamodb-check" = {
      handler = "dr_switch.dynamodb.handlers.check"
      env     = { REGION = var.self_region, TABLE_NAMES = jsonencode(var.self_table_names) }
      policy = [{
        actions   = ["dynamodb:DescribeTable"]
        resources = local.self_table_arns
      }]
    }

    # --- NLB / CloudWatch --------------------------------------------------
    # どちらもリソースレベル権限に非対応のため "*" になる。AWS のマネージド
    # ポリシー AmazonECSInfrastructureRolePolicyForLoadBalancers でも
    # Describe 系だけ "*"、RegisterTargets 等は ARN 指定になっている。
    "nlb-check" = {
      handler = "dr_switch.nlb.handlers.check"
      env = {
        REGION             = var.self_region
        TARGET_GROUP_ARNS  = jsonencode(var.self_target_group_arns)
        LOAD_BALANCER_ARNS = jsonencode(var.self_load_balancer_arns)
      }
      policy = [{
        actions = [
          "elasticloadbalancing:DescribeLoadBalancers",
          "elasticloadbalancing:DescribeTargetHealth",
        ]
        resources = ["*"]
      }]
    }

    "cloudwatch-check" = {
      handler = "dr_switch.cloudwatch.handlers.check"
      env     = { REGION = var.self_region, ALARM_PREFIX = var.alarm_prefix }
      policy = [{
        actions   = ["cloudwatch:DescribeAlarms"]
        resources = ["*"]
      }]
    }

    # --- EFS ---------------------------------------------------------------
    "efs-check" = {
      handler = "dr_switch.efs.handlers.check"
      env = {
        REGION          = var.self_region
        FILE_SYSTEM_IDS = jsonencode(var.self_file_system_ids)
      }
      policy = [{
        actions = [
          "elasticfilesystem:DescribeFileSystems",
          "elasticfilesystem:DescribeMountTargets",
        ]
        resources = local.self_file_system_arns
      }]
    }

    # --- EKS ---------------------------------------------------------------
    # ワークロードの参照・更新権限は IAM ではなく Kubernetes RBAC 側
    # （eks_access.tf）。IAM 側は kubeconfig 生成に必要な分だけ。
    "eks-check" = {
      handler = "dr_switch.eks.handlers.check"
      env     = { REGION = var.self_region, EKS_CLUSTERS = jsonencode(var.eks_clusters) }
      policy  = local.eks_access_policy
    }

    "eks-rollout-restart" = {
      handler = "dr_switch.eks.handlers.rollout_restart"
      env     = { REGION = var.self_region, EKS_CLUSTERS = jsonencode(var.eks_clusters) }
      policy  = local.eks_access_policy
    }

    # 呼ばれる側は Pod の起動完了を待つため、その Timeout を上回る値にする
    "eks-restart-pods" = {
      handler = "dr_switch.eks.handlers.restart_pods"
      env = {
        REGION                = var.self_region
        POD_RESTART_FUNCTIONS = jsonencode(var.pod_restart_function_names)
        POD_RESTART_TIMEOUT   = tostring(var.pod_restart_timeout)
      }
      timeout = var.pod_restart_timeout + 60
      policy = [{
        actions   = ["lambda:InvokeFunction"]
        resources = local.pod_restart_arns
      }]
    }
  }

  # eks-check と eks-rollout-restart で共通
  eks_access_policy = [
    {
      actions   = ["eks:DescribeCluster"]
      resources = local.self_cluster_arns
    },
    {
      actions   = ["sts:GetCallerIdentity"]
      resources = ["*"]
    },
  ]

  # Kubernetes RBAC のグループにマッピングする関数
  eks_functions = ["eks-check", "eks-rollout-restart"]
}
