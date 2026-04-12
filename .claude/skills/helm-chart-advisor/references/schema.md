# values.schema.json ルール

本リファレンスでは `values.schema.json` の構造と、`values.yaml` との整合性に関するルールを定める。

個別のプロパティに対する制約（`const`、`enum`、`patternProperties` 等）は各ドメインリファレンスで定義されており、各ドメインリファレンスのレビューステップで検査される。本リファレンスはスキーマ全体の構造と `values.yaml` との整合性のみを扱う。

---

## スキーマの基本構造

`values.schema.json` は以下の構造で記述する。

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": [...],
  "properties": {
    ...
  },
  "additionalProperties": false
}
```

- `$schema` は `https://json-schema.org/draft/2020-12/schema` を使用する
- ルートの `type` は `"object"` とする
- `additionalProperties: false` をルートに設定し、未定義キーの混入を防ぐ
- ネストされたオブジェクト型プロパティにも `additionalProperties: false` を設定する

理由:
- `additionalProperties: false` がないと、typo によるキー名ミス（`replicCount` 等）が検出されず、デフォルト値にフォールバックして意図しない挙動になる。

---

## values.yaml との双方向整合性

**`values.yaml` の全キーと `values.schema.json` の全プロパティは 1:1 で対応しなければならない。**

### values.yaml → values.schema.json 方向

`values.yaml` に定義されているすべてのキーに対して、`values.schema.json` に対応する `properties` エントリが存在すること。スキーマに定義がないキーは `additionalProperties: false` により `helm install` 時にエラーとなるため、values.yaml にキーを追加したら必ずスキーマも更新する。

### values.schema.json → values.yaml 方向

`values.schema.json` の `properties` に定義されているすべてのキーに対して、`values.yaml` に対応するキーとデフォルト値が存在すること。スキーマにだけ存在してデフォルト値がないキーは、利用者が `values.yaml` を見て設定可能なパラメータを把握できなくなる。

### レビュー時のチェック方法

整合性チェックは以下の手順で行う:

1. `values.yaml` のトップレベルキーを列挙する
2. `values.schema.json` の `properties` のトップレベルキーを列挙する
3. 片方にしか存在しないキーを違反として報告する
4. ネストされたオブジェクト型キーについても再帰的に同じチェックを行う

---

## required の設定

`required` 配列には、デフォルト値が空文字列 `""` またはチャートの動作に必須のキーを列挙する。`values.yaml` にデフォルト値が設定されていても、利用者による上書きが必須のキー（例: `image.repository`）は `required` に含める。

どのキーを `required` にすべきかは、各ドメインリファレンスの指定に従う。

---

## 型定義のルール

各プロパティの `type` は `values.yaml` のデフォルト値の型と一致させる。

| values.yaml のデフォルト値 | schema の `type` |
|---|---|
| `true` / `false` | `"boolean"` |
| `80` | `"integer"` |
| `"example.com"` | `"string"` |
| `{}` | `"object"` |
| `[]` | `"array"` |

空オブジェクト `{}` のプロパティ（`podAnnotations: {}`、`nodeSelector: {}` 等、利用者が自由にキーを追加する pass-through 型）は、`additionalProperties` でキー・値の型を指定する。

```json
"podAnnotations": {
  "type": "object",
  "additionalProperties": {
    "type": "string"
  }
}
```

pass-through 型プロパティでは `additionalProperties: false` を設定しない。利用者が任意のキーを追加できることが目的であるため。

