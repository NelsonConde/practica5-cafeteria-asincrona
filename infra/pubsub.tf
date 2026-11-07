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

resource "google_service_account" "cocina" {
  account_id   = "${var.prefijo}-cocina"
  display_name = "Cocina de la cafetería"

  depends_on = [google_project_service.apis]
}

resource "google_project_iam_member" "cocina_firestore" {
  project = var.proyecto
  role    = "roles/datastore.user"
  member  = google_service_account.cocina.member
}

resource "google_cloud_run_v2_service" "cocina" {
  name                = "${var.prefijo}-cocina"
  location            = var.region
  deletion_protection = false

  template {
    service_account = google_service_account.cocina.email

    scaling {
      max_instance_count = 3
    }

    # Tantas peticiones a la vez como hilos tiene gunicorn en la cocina.
    max_instance_request_concurrency = 8

    containers {
      image = var.imagen_cocina

      env {
        name  = "BASE_DATOS"
        value = google_firestore_database.cafeteria.name
      }
    }
  }

  depends_on = [
    google_project_service.apis,
    google_project_iam_member.cocina_firestore,
  ]
}

data "google_project" "actual" {}

locals {
  agente_pubsub = "serviceAccount:service-${data.google_project.actual.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_service_account" "invocador" {
  account_id   = "${var.prefijo}-invocador"
  display_name = "Pub/Sub invoca a la cocina"

  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_v2_service_iam_member" "invocador_cocina" {
  name     = google_cloud_run_v2_service.cocina.name
  location = google_cloud_run_v2_service.cocina.location
  role     = "roles/run.invoker"
  member   = google_service_account.invocador.member
}

resource "google_service_account_iam_member" "pubsub_firma_tokens" {
  service_account_id = google_service_account.invocador.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = local.agente_pubsub

  # El agente de Pub/Sub aparece cuando se usa la API por primera vez.
  depends_on = [google_pubsub_topic.pedidos]
}

resource "google_pubsub_subscription" "cocina" {
  name  = "${var.prefijo}-cocina"
  topic = google_pubsub_topic.pedidos.id

  ack_deadline_seconds = 60

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "60s"
  }

  push_config {
    push_endpoint = google_cloud_run_v2_service.cocina.uri

    oidc_token {
      service_account_email = google_service_account.invocador.email
      audience              = google_cloud_run_v2_service.cocina.uri
    }
  }

  depends_on = [
    google_cloud_run_v2_service_iam_member.invocador_cocina,
    google_service_account_iam_member.pubsub_firma_tokens,
  ]
}