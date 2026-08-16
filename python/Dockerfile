# 13 本の Lambda で同一イメージを共有し、image_config.command でハンドラを
# 切り替える。Lambda はコンテナイメージをダイジェスト単位でゾーン／ワーカー
# キャッシュするため、イメージを共有すると最初の 1 本がキャッシュを温め、
# 残りがその恩恵を受ける。DR 切替はキャッシュが冷えた状態で 13 本を連続実行
# するため、分割すると初回ペナルティを 13 回払うことになる。
FROM public.ecr.aws/lambda/python:3.13

# eks の check が使う AWS CLI。他の関数では未使用だが、上記の理由により
# イメージは分割しない。
RUN dnf install -y unzip tar gzip \
 && curl -sSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip \
 && unzip -q /tmp/awscliv2.zip -d /tmp \
 && /tmp/aws/install \
 && rm -rf /tmp/awscliv2.zip /tmp/aws \
 && dnf clean all

COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

COPY dr_switch/ ${LAMBDA_TASK_ROOT}/dr_switch/

# ハンドラは Terraform の image_config.command で関数ごとに上書きする。
#   例: command = ["dr_switch.nlb.handlers.check"]
CMD ["dr_switch.apigateway.handlers.block"]
