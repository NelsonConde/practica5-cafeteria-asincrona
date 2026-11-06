variable "proyecto" {
  description = "ID del proyecto de Google Cloud"
  type        = string
}

variable "prefijo" {
  description = "Prefijo para los nombres de los recursos, por ejemplo grupo3"
  type        = string

  # Las cuentas de servicio admiten como máximo 30 caracteres. Con 12 para el
  # prefijo quedan 18 para el sufijo, suficiente para nombres como
  # "-cocina" o "-invocador-cocina".
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,10}[a-z0-9]$", var.prefijo))
    error_message = "El prefijo debe tener entre 3 y 12 caracteres, empezar por una letra minúscula y usar solo minúsculas, números y guiones (sin guion al final)."
  }
}

variable "region" {
  description = "Región para Cloud Run, Artifact Registry y Firestore"
  type        = string
  default     = "us-central1"
}

variable "imagen_backend" {
  description = "Imagen del backend en Artifact Registry, con su etiqueta"
  type        = string
}

variable "imagen_frontend" {
  description = "Imagen del frontend en Artifact Registry, con su etiqueta"
  type        = string
}
