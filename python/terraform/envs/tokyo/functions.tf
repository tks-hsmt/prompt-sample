# ============================================================================
# 対象 Lambda の定義（追加・変更はここだけ）
#
# 関数を増やすときは local.functions にエントリを 1 つ足す。module 配下には
# 手を入れない。
#
#   handler  コンテナイメージの image_config.command に渡すハンドラ
#   env      環境変数。REGION は必須
#   policy   IAM ポリシーのステートメント配列
#              actions            必須
#              resources          必須
#              pass_role_service  任意。iam:PassRole の渡し先を限定する
#   timeout  任意。既定 60 秒
#   vpc      任意。既定 true
#   eks      任意。既定 false。true なら EKS アクセスエントリを作る
# ============================================================================

locals {
  functions = {
    # --- API Gateway -------------------------------------------------------
    "apigateway-block" = {
      handler = "dr_switch.apigateway.handlers.block"
      env = {
        REGION      = local.peer_region
        REST_API_ID = local.peer_api.id
        STAGE       = local.peer_api.stage
      }
      policy = [{
        actions   = ["apigateway:GET", "apigateway:PATCH"]
        resources = [local.peer_stage_arn]
      }]
    }

    "apigateway-enable" = {
      handler = "dr_switch.apigateway.handlers.enable"
      env = {
        REGION         = local.self_region
        REST_API_ID    = local.self_api.id
        STAGE          = local.self_api.stage
        THROTTLE_RATE  = "10000"
        THROTTLE_BURST = "5000"
      }
      policy = [{
        actions   = ["apigateway:GET", "apigateway:PATCH"]
        resources = [local.self_stage_arn]
      }]
    }

    # get-rest-api（apiStatus）と get-stage（スロットリング値）で対象が違う
    "apigateway-check" = {
      handler = "dr_switch.apigateway.handlers.check"
      env = {
        REGION         = local.self_region
        REST_API_ID    = local.self_api.id
        STAGE          = local.self_api.stage
        THROTTLE_RATE  = "10000"
        THROTTLE_BURST = "5000"
      }
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
      env     = { REGION = local.peer_region, SCHEDULE_GROUP = local.peer_group }
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
      env     = { REGION = local.self_region, SCHEDULE_GROUP = local.self_group }
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
      env     = { REGION = local.self_region, SCHEDULE_GROUP = local.self_group }
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
        REGION              = local.peer_region
        REPLICATION_BUCKETS = jsonencode(local.peer_buckets)
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
        REGION              = local.self_region
        REPLICATION_BUCKETS = jsonencode(local.self_buckets)
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
        REGION              = local.self_region
        REPLICATION_BUCKETS = jsonencode(local.self_buckets)
      }
      policy = [{
        actions   = ["s3:GetReplicationConfiguration"]
        resources = local.self_bucket_arns
      }]
    }

    # --- Lambda / DynamoDB -------------------------------------------------
    # GetFunction ではなく GetFunctionConfiguration。応答が軽く権限も狭い
    "lambda-check" = {
      handler = "dr_switch.lambda_function.handlers.check"
      env = {
        REGION         = local.self_region
        FUNCTION_NAMES = jsonencode(local.self_function_names)
      }
      policy = [{
        actions   = ["lambda:GetFunctionConfiguration"]
        resources = local.self_function_arns
      }]
    }

    "dynamodb-check" = {
      handler = "dr_switch.dynamodb.handlers.check"
      env     = { REGION = local.self_region, TABLE_NAMES = jsonencode(local.self_table_names) }
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
        REGION             = local.self_region
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
      env     = { REGION = local.self_region, ALARM_PREFIX = local.alarm_prefix }
      policy = [{
        actions   = ["cloudwatch:DescribeAlarms"]
        resources = ["*"]
      }]
    }

    # --- EFS ---------------------------------------------------------------
    "efs-check" = {
      handler = "dr_switch.efs.handlers.check"
      env = {
        REGION          = local.self_region
        FILE_SYSTEM_IDS = jsonencode(local.self_file_system_ids)
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
    # ワークロードの参照・更新権限は IAM ではなく Kubernetes RBAC 側。
    # IAM 側は kubeconfig 生成に必要な分だけ。
    "eks-check" = {
      handler = "dr_switch.eks.handlers.check"
      env     = { REGION = local.self_region, EKS_CLUSTERS = jsonencode(local.eks_clusters_env) }
      eks     = true
      policy  = local.eks_access_policy
    }

    "eks-rollout-restart" = {
      handler = "dr_switch.eks.handlers.rollout_restart"
      env     = { REGION = local.self_region, EKS_CLUSTERS = jsonencode(local.eks_clusters_env) }
      eks     = true
      policy  = local.eks_access_policy
    }

    # 呼ばれる側は Pod の起動完了を待つため、その Timeout を上回る値にする
    "eks-restart-pods" = {
      handler = "dr_switch.eks.handlers.restart_pods"
      env = {
        REGION                = local.self_region
        POD_RESTART_FUNCTIONS = jsonencode(local.pod_restart_function_names)
        POD_RESTART_TIMEOUT   = tostring(local.pod_restart_timeout)
      }
      timeout = local.pod_restart_timeout + 60
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
}
