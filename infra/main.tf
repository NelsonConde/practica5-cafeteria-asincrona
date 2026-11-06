# APIs del proyecto. Pub/Sub se habilita desde ya porque tarda unos minutos
# y así no hay que esperarla en clase. Resource Manager la usa Terraform para
# leer datos del proyecto. disable_on_destroy = false evita que un destroy
# apague APIs que otros recursos del proyecto podrían estar usando.
resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "firestore.googleapis.com",
    "iam.googleapis.com",
    "pubsub.googleapis.com",
    "cloudresourcemanager.googleapis.com",
  ])

  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "registro" {
  repository_id = "${var.prefijo}-imagenes"
  location      = var.region
  format        = "DOCKER"

  depends_on = [google_project_service.apis]
}

# Una base con nombre propio, para no chocar con la base (default) ni con la
# de otras prácticas en el mismo proyecto.
resource "google_firestore_database" "cafeteria" {
  name                    = "${var.prefijo}-cafeteria"
  location_id             = var.region
  type                    = "FIRESTORE_NATIVE"
  delete_protection_state = "DELETE_PROTECTION_DISABLED"
  deletion_policy         = "DELETE"

  depends_on = [google_project_service.apis]
}

# ---------- Backend ----------

resource "google_service_account" "backend" {
  account_id   = "${var.prefijo}-backend"
  display_name = "Backend de la cafetería"

  depends_on = [google_project_service.apis]
}

resource "google_project_iam_member" "backend_firestore" {
  project = var.proyecto
  role    = "roles/datastore.user"
  member  = google_service_account.backend.member
}

resource "google_cloud_run_v2_service" "backend" {
  name                = "${var.prefijo}-backend"
  location            = var.region
  deletion_protection = false

  template {
    service_account = google_service_account.backend.email

    scaling {
      max_instance_count = 3
    }

    containers {
      image = var.imagen_backend

      env {
        name  = "BASE_DATOS"
        value = google_firestore_database.cafeteria.name
      }
    }
  }

  # El backend prepara el inventario al arrancar, así que necesita el permiso
  # sobre Firestore antes de que exista la primera instancia.
  depends_on = [
    google_project_service.apis,
    google_project_iam_member.backend_firestore,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "backend_publico" {
  name     = google_cloud_run_v2_service.backend.name
  location = google_cloud_run_v2_service.backend.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ---------- Frontend ----------

# El frontend no llama a ninguna API de Google: su cuenta no tiene roles.
# Existe para que no use la cuenta por defecto de Compute Engine, que tiene
# permisos de más.
resource "google_service_account" "frontend" {
  account_id   = "${var.prefijo}-frontend"
  display_name = "Frontend de la cafetería"

  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_v2_service" "frontend" {
  name                = "${var.prefijo}-frontend"
  location            = var.region
  deletion_protection = false

  template {
    service_account = google_service_account.frontend.email

    scaling {
      max_instance_count = 2
    }

    containers {
      image = var.imagen_frontend

      env {
        name  = "BACKEND_URL"
        value = google_cloud_run_v2_service.backend.uri
      }
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_v2_service_iam_member" "frontend_publico" {
  name     = google_cloud_run_v2_service.frontend.name
  location = google_cloud_run_v2_service.frontend.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}
