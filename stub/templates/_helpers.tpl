{{/*
共通ラベル
*/}}
{{- define "com-notifier-stub.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
セレクタラベル
*/}}
{{- define "com-notifier-stub.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
イメージ参照
*/}}
{{- define "com-notifier-stub.image" -}}
{{ .Values.image.repository }}:{{ .Values.image.tag }}
{{- end }}
