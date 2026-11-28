# Système de trade entre joueurs

_Fiche sortie de CLAUDE.md le 28/11/2026 (audit) : texte inchangé, liens recalés._

- **Modèle DB** : tables `trades` (initiator/target_player_id, status, or offerts, expires_at) et `trade_items` (offered_by initiator/target, item_definition_id, quantity, `gear_id` pour une pièce d'équipement — cf. équipement v2).
- **Statuts** : `pending`, `accepted`, `refused`, `cancelled`, `expired`, `failed` (ressources manquantes à l'accept).
- **Sécurité atomique** : `AcceptTradeUseCase` revérifie les ressources des **deux** joueurs au moment de l'acceptation, pas seulement à la proposition. Si l'un manque de quoi que ce soit → status `failed`, aucun déplacement.
- **TTL** : 5 minutes par défaut. Au-delà, status devient `expired` à la prochaine tentative d'acceptation OU à la prochaine itération du cleanup loop côté bot (`TradeCog.expire_loop`, `tasks.loop(minutes=1)` qui appelle `TradeRepository.expire_overdue_pending` — bulk UPDATE WHERE status=pending AND expires_at < now). Idempotent.
- **Un trade pending par paire** : si Alice→Bob a un trade pending, ni Alice→Bob ni Bob→Alice ne peuvent en proposer un nouveau. Annuler ou attendre l'expiration (le cleanup loop libère automatiquement après 5 min).
- **UI** : `/echange @joueur` → brouillon ephemeral itératif ([`TradeDraftView`](../../app/bot/views/trade_draft_view.py)) avec 7 boutons. Pas de saisie manuelle de codes : Select Menus listant l'inventaire de l'initiateur ou de la cible (top 25 par quantité), puis modal de quantité. Boutons gold ouvrent une modal mono-champ. Sur Submit → trade créé + message public avec embed + `TradeResponseView` (Accept/Refuse/Cancel) dans [`trade_view.py`](../../app/bot/views/trade_view.py).
