-- Wipe complet des items + panoplies (repartir de zéro via le site admin).
-- Vide item_definitions ET toutes les tables qui référencent un item, puis
-- remet à [] le loot de tous les mobs (les mobs eux-mêmes sont CONSERVÉS).
-- À exécuter APRÈS avoir sauvegardé la base :  cp lita_v2.db lita_v2_backup_*.db
-- Usage :  sqlite3 lita_v2.db < scripts/wipe_items.sql
PRAGMA foreign_keys=OFF;
DELETE FROM player_inventory_items;
DELETE FROM player_equipment;
DELETE FROM player_equipment_set_items;
DELETE FROM player_equipment_sets;
DELETE FROM trade_items;
DELETE FROM trades;
DELETE FROM marketplace_listings;
DELETE FROM shop_items;
DELETE FROM craft_recipe_ingredients;
DELETE FROM craft_recipes;
DELETE FROM item_definitions;
UPDATE mob_definitions SET loot_table_json='[]';
