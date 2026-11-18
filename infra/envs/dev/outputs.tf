output "name_prefix" {
  description = "Prefix of every named resource in this root (INF-NAME-1). Module calls added by later specs take it as an input."
  value       = local.name_prefix
}
