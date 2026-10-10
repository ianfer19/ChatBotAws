# Tablas operacionales del chatbot, una por familia de dato (DATA_MODEL §DynamoDB).
#
# On-demand (sin provisionar capacidad: volumen inicial bajo y coste
# predecible), TTL `ttl` donde la tabla expira y cifrado en reposo con la llave
# del entorno cuando se pasa. Sin GSI por ahora: las consultas van por
# PK/SK; si el adapter del Paso 8 necesita otra ruta → TODO(verify).

resource "aws_dynamodb_table" "tabla" {
  for_each     = var.tables
  name         = "${each.key}_${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = each.value.pk

  attribute {
    name = each.value.pk
    type = "S"
  }

  dynamic "attribute" {
    for_each = each.value.sk == null ? [] : [each.value.sk]

    content {
      name = attribute.value
      type = "S"
    }
  }

  dynamic "ttl" {
    for_each = each.value.ttl == null ? [] : [each.value.ttl]

    content {
      attribute_name = ttl.value
      enabled        = true
    }
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }
}
