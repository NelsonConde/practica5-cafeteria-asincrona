resource "google_pubsub_topic" "pedidos" {
  name = "${var.prefijo}-pedidos"

  depends_on = [google_project_service.apis]
}

# El backend puede publicar en este tema y en ningún otro.
resource "google_pubsub_topic_iam_member" "backend_publica" {
  topic  = google_pubsub_topic.pedidos.name
  role   = "roles/pubsub.publisher"
  member = google_service_account.backend.member
}