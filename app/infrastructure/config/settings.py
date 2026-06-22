from pydantic_settings import BaseSettings, SettingsConfigDict


# Valeur sentinelle : si admin_session_secret reste à ça, la webapp refuse de démarrer.
# Un secret connu publiquement permet de forger un cookie admin et de bypass l'auth.
ADMIN_SESSION_SECRET_DEFAULT = "dev-secret-change-in-prod"


class Settings(BaseSettings):
    discord_token: str
    database_url: str
    env: str = "development"
    debug: bool = True
    beta_channel_id: int
    encounter_channel_id: int
    # Channel dédié aux world bosses. Optionnel pour rester rétrocompatible
    # avec les .env existants qui n'ont pas encore l'ID. Si 0/None, fallback
    # vers encounter_channel_id (les bosses sortent dans le même canal).
    boss_channel_id: int = 0
    # URL publique du webapp skill tree (utilisée par le bouton 'Vue détaillée'
    # de /skill). Sans valeur, on retombe sur l'URL locale http://localhost:8000.
    webapp_base_url: str = "http://localhost:8000"
    admin_discord_ids: str = ""

    # Discord OAuth2 — utilisé par la webapp admin pour authentifier les
    # utilisateurs via leur compte Discord. Récupère client_id/secret
    # depuis la Discord Developer Portal (section OAuth2 de l'app).
    discord_client_id: str = ""
    discord_client_secret: str = ""
    # URL publique du redirect OAuth (à enregistrer dans Discord Portal
    # > OAuth2 > Redirects). Ex : http://151.80.233.231:8001/admin/auth/callback
    oauth_redirect_uri: str = "http://localhost:8001/admin/auth/callback"
    # Clé pour signer les cookies de session admin. Générer avec
    # `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
    # Le défaut est volontairement reconnaissable : la webapp refuse de démarrer
    # tant qu'on ne l'a pas redéfini dans .env (assert_safe_secret()).
    admin_session_secret: str = ADMIN_SESSION_SECRET_DEFAULT

    # Cookies de session/oauth en `Secure` (HTTPS only). Mettre à True en prod
    # derrière TLS. Laisser False en local HTTP (sinon le cookie n'est jamais
    # envoyé et le login boucle).
    admin_cookie_secure: bool = False

    # Si True, les éditions de contenu via l'admin web sont commitées + poussées
    # sur git (beta). Nécessite une clé de déploiement write sur le VPS.
    # Désactivé par défaut : le contenu est tout de même écrit dans les JSON
    # locaux (reseed-safe) même sans push.
    content_git_push: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def admin_ids(self) -> list[int]:
        if not self.admin_discord_ids:
            return []
        return [
            int(part.strip())
            for part in self.admin_discord_ids.split(",")
            if part.strip()
        ]

    def assert_safe_admin_secret(self) -> None:
        """Refuse de démarrer si le secret de signature de cookie est resté au défaut.
        Sans ça, n'importe qui peut forger un cookie admin via le secret public du repo."""
        if self.admin_session_secret == ADMIN_SESSION_SECRET_DEFAULT:
            raise RuntimeError(
                "admin_session_secret est au défaut public — refuse de démarrer. "
                "Générez un secret : python -c 'import secrets; print(secrets.token_urlsafe(32))' "
                "et définissez ADMIN_SESSION_SECRET dans .env."
            )


settings = Settings()