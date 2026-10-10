# Bucket de archivo de conversaciones y media (DATA_MODEL §S3).
#
# Un único bucket por entorno con prefijos por tenant
# (<tenant_id>/conversations/... y <tenant_id>/media/...): el aislamiento por
# prefijo lo exige MULTI_TENANCY §4. Bloqueo público total, cifrado en reposo y
# solo-TLS. Lifecycle y retención → TODO(verify) hasta cerrar ADR 0007.

data "aws_caller_identity" "current" {}

locals {
  # El namespace de S3 es global: el id de cuenta evita colisiones con otros
  # proyectos que usen el mismo prefijo.
  bucket_name = "${var.name_prefix}-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket" "archivo" {
  bucket        = local.bucket_name
  force_destroy = false
}

# Sin ACLs: los permisos se gestionan solo con políticas de bucket e IAM
# (BucketOwnerEnforced), una fuente menos de errores de estilo «todo público».
resource "aws_s3_bucket_ownership_controls" "archivo" {
  bucket = aws_s3_bucket.archivo.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "archivo" {
  bucket                  = aws_s3_bucket.archivo.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# SSE-KMS siempre: con `kms_key_arn` usa la llave del entorno; sin él, la llave
# gestionada por S3 (`aws/s3`). Bucket key activa para abaratar los llamados KMS.
resource "aws_s3_bucket_server_side_encryption_configuration" "archivo" {
  bucket = aws_s3_bucket.archivo.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_policy" "solo_tls" {
  bucket = aws_s3_bucket.archivo.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.archivo.arn,
          "${aws_s3_bucket.archivo.arn}/*",
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      },
    ]
  })
}
