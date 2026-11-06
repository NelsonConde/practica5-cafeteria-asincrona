output "registro" {
  description = "Ruta del registro para etiquetar las imágenes"
  value       = "${var.region}-docker.pkg.dev/${var.proyecto}/${google_artifact_registry_repository.registro.repository_id}"
}

output "url_backend" {
  value = google_cloud_run_v2_service.backend.uri
}

output "url_frontend" {
  value = google_cloud_run_v2_service.frontend.uri
}
