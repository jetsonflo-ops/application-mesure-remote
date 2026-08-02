"""Types d'erreurs et categories pour le systeme de notification.

Chaque erreur appartient a une categorie et porte un message
humain, clair, sans code technique.
"""

from __future__ import annotations

from enum import Enum, auto
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


class ErrorCategory(Enum):
    """Categories d'erreurs de l'application."""
    BLUETOOTH = auto()        # Connexion BLE, scan, pairing
    EXPORT = auto()           # Export de fichiers (XLSX, CSV, etc.)
    FICHIER = auto()          # Lecture/ecriture fichier de config, etc.
    BASE_DONNEES = auto()     # SQLite, stockage
    RESEAU = auto()           # Connexion reseau, API
    APPLICATION = auto()      # Erreur interne, demarrage, arret
    MATERIEL = auto()         # Peripherique, capteur, outil


# Messages d'erreur predefinis par type (humains, sans code)
ERROR_MESSAGES: dict[tuple[ErrorCategory, str], str] = {
    # Bluetooth
    (ErrorCategory.BLUETOOTH, "scan_failed"):
        "Le scan Bluetooth n'a pas pu demarrer. Verifiez que "
        "le Bluetooth est active sur votre appareil.",
    (ErrorCategory.BLUETOOTH, "connection_failed"):
        "Impossible de se connecter a l'appareil Bluetooth. "
        "Verifiez qu'il est allume et a proximite.",
    (ErrorCategory.BLUETOOTH, "device_unreachable"):
        "L'appareil Bluetooth est hors de portee ou a ete "
        "eteint. Rapprochez-vous et reessayez.",
    (ErrorCategory.BLUETOOTH, "pairing_failed"):
        "Le jumelage avec l'appareil Bluetooth a echoue. "
        "Verifiez le code PIN ou les parametres de securite.",
    (ErrorCategory.BLUETOOTH, "gatt_error"):
        "Erreur de communication avec l'appareil Bluetooth. "
        "Deconnectez et reconnectez l'appareil.",
    (ErrorCategory.BLUETOOTH, "disconnected"):
        "Connexion Bluetooth perdue. Tentative de "
        "reconnexion automatique en cours.",
    (ErrorCategory.BLUETOOTH, "no_adapter"):
        "Aucun adaptateur Bluetooth trouve sur ce systeme. "
        "Verifiez votre materiel Bluetooth.",
    (ErrorCategory.BLUETOOTH, "timeout"):
        "Le temps d'attente pour l'appareil Bluetooth "
        "est expire. Verifiez sa disponibilite.",
    (ErrorCategory.BLUETOOTH, "data_parse"):
        "Les donnees recues de l'appareil Bluetooth sont "
        "invalides. Verifiez le format de mesure attendu.",

    # Export
    (ErrorCategory.EXPORT, "disk_full"):
        "Le disque de destination est plein. Liberez de "
        "l'espace pour pouvoir exporter les mesures.",
    (ErrorCategory.EXPORT, "permission_denied"):
        "Permission refusee pour ecrire dans le dossier "
        "d'export. Verifiez les droits d'acces.",
    (ErrorCategory.EXPORT, "format_error"):
        "Une erreur est survenue lors de la generation du "
        "fichier. Verifiez les parametres d'export.",
    (ErrorCategory.EXPORT, "file_locked"):
        "Le fichier d'export est deja ouvert par un autre "
        "programme. Fermez-le puis reessayez.",
    (ErrorCategory.EXPORT, "library_missing"):
        "Une bibliotheque necessaire a l'export est "
        "manquante. Reinstallez l'application.",
    (ErrorCategory.EXPORT, "path_not_found"):
        "Le dossier d'export n'existe pas et n'a pas pu "
        "etre cree. Verifiez le chemin.",

    # Fichier
    (ErrorCategory.FICHIER, "read_failed"):
        "Impossible de lire le fichier. Verifiez qu'il "
        "existe et qu'il n'est pas corrompu.",
    (ErrorCategory.FICHIER, "write_failed"):
        "Impossible d'ecrire le fichier. Verifiez les "
        "permissions et l'espace disque.",
    (ErrorCategory.FICHIER, "config_corrupt"):
        "Le fichier de configuration est corrompu. "
        "Les parametres par defaut seront utilises.",
    (ErrorCategory.FICHIER, "not_found"):
        "Le fichier demande n'a pas ete trouve. "
        "Verifiez le chemin et le nom du fichier.",

    # Base de donnees
    (ErrorCategory.BASE_DONNEES, "connection_failed"):
        "Connexion a la base de donnees echouee. "
        "L'application va redemarrer la base.",
    (ErrorCategory.BASE_DONNEES, "query_failed"):
        "Erreur lors de la lecture des donnees. "
        "Les donnees affichees peuvent etre incompletes.",
    (ErrorCategory.BASE_DONNEES, "corrupt"):
        "La base de donnees semble corrompue. "
        "Une reinitialisation peut etre necessaire.",

    # Reseau
    (ErrorCategory.RESEAU, "no_connection"):
        "Pas de connexion reseau. Certaines "
        "fonctionnalites peuvent etre indisponibles.",
    (ErrorCategory.RESEAU, "timeout"):
        "Le serveur ne repond pas. Verifiez votre "
        "connexion internet et reessayez.",
    (ErrorCategory.RESEAU, "api_error"):
        "Erreur de communication avec le service distant. "
        "Reessayez plus tard.",

    # Application
    (ErrorCategory.APPLICATION, "startup"):
        "Erreur au demarrage de l'application. "
        "Certaines fonctionnalites peuvent etre reduites.",
    (ErrorCategory.APPLICATION, "internal"):
        "Une erreur interne est survenue. "
        "Redemarrez l'application si le probleme persiste.",
    (ErrorCategory.APPLICATION, "unknown"):
        "Une erreur inattendue est survenue. "
        "Si le probleme persiste, contactez le support.",

    # Materiel
    (ErrorCategory.MATERIEL, "not_found"):
        "L'outil de mesure n'est pas disponible. "
        "Verifiez la connexion de votre appareil.",
    (ErrorCategory.MATERIEL, "disconnected"):
        "L'outil de mesure a ete deconnecte. "
        "Reconnectez-le pour continuer les mesures.",
    (ErrorCategory.MATERIEL, "battery_low"):
        "La batterie de l'appareil de mesure est "
        "faible. Pensez a le recharger.",
}


def get_error_message(category: ErrorCategory, error_type: str) -> str:
    """Retourne le message utilisateur pour une erreur.

    Si le type d'erreur n'est pas dans le dictionnaire,
    un message generique est utilise.
    """
    key = (category, error_type)
    if key in ERROR_MESSAGES:
        return ERROR_MESSAGES[key]
    # Fallback generique par categorie
    fallback = {
        ErrorCategory.BLUETOOTH:
            "Une erreur Bluetooth est survenue. Verifiez "
            "vos appareils et reessayez.",
        ErrorCategory.EXPORT:
            "Une erreur d'export est survenue. Verifiez "
            "le dossier de destination et reessayez.",
        ErrorCategory.FICHIER:
            "Une erreur fichier est survenue. Verifiez "
            "les permissions et reessayez.",
        ErrorCategory.BASE_DONNEES:
            "Une erreur de base de donnees est survenue. "
            "L'application va tenter de la reparer.",
        ErrorCategory.RESEAU:
            "Une erreur reseau est survenue. Verifiez "
            "votre connexion et reessayez.",
        ErrorCategory.APPLICATION:
            "Une erreur application est survenue. "
            "Redemarrez si le probleme persiste.",
        ErrorCategory.MATERIEL:
            "Une erreur materiel est survenue. Verifiez "
            "vos peripheriques et reessayez.",
    }
    return fallback.get(category, "Une erreur est survenue.")


@dataclass
class ErrorInfo:
    """Instance d'erreur (unique par type)."""
    category: ErrorCategory
    error_type: str
    message: str
    count: int = 1
    first_seen: datetime = field(default_factory=datetime.now)
    last_seen: datetime = field(default_factory=datetime.now)
    active: bool = True  # False = ferme par l'utilisateur
