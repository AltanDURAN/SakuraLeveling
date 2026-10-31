"""Tutoriel `/tuto` (31/10/2026, demande de l'auteur) : on découvre tout le
bot avec Hana, la gardienne du Grand Cerisier, en faisant les choses pour
de vrai. Au bout : l'aventure commence, et 3 potions de soin qui rendent
100 % des PV (une seule fois par joueur).

Chaque étape a un récit (RP), des actions à faire et, quand c'est possible,
une VÉRIFICATION (`check`) faite par l'application sur la base du joueur :
le bouton « C'est fait » ne passe à la suite que si l'action est réellement
faite. Une étape peut toujours être passée (un combat qui ne vient pas, un
salon pas encore ouvert…) : la récompense n'exige que d'aller au bout.
"""

from __future__ import annotations

from dataclasses import dataclass

GUIDE_NAME = "Hana, gardienne du Grand Cerisier"
REWARD_ITEM = "potion_soin_totale"
REWARD_QUANTITY = 3


@dataclass(frozen=True)
class TutorialStep:
    code: str
    emoji: str
    title: str
    story: str                  # ce que dit Hana
    actions: tuple[str, ...]    # ce que le joueur fait ({zone} = salon de la 1re zone)
    check: str = ""             # vérification (cf. use_cases/tutorial.CHECKS), "" = lecture
    hint: str = ""              # si la vérification échoue


STEPS: tuple[TutorialStep, ...] = (
    TutorialStep(
        "arrivee", "🌸", "L'arrivée au Grand Cerisier",
        "Ah, te voilà enfin ! Les pétales m'avaient prévenue de ton arrivée. Je suis **Hana**, "
        "gardienne du Grand Cerisier. Autour de nous, des monstres sortent des terres sauvages : "
        "il nous faut des aventuriers. Ton nom est désormais inscrit dans le **registre** de la "
        "guilde, au **Rang F**, le premier. Chaque rang t'ouvrira une nouvelle région.",
        ("Regarde ta fiche d'aventurier : **`/profil`** (niveau, rang, puissance, stats).",
         "Ta puissance (PWR) résume ta force : c'est elle qui ouvrira les épreuves de rang."),
    ),
    TutorialStep(
        "daily", "📜", "La bourse du voyageur",
        "Un aventurier sans le sou ne va pas loin. Chaque jour, la guilde verse une **solde** à "
        "ceux qui passent la voir. Reviens tous les jours : ta **série** grossit la récompense… "
        "mais chaque jour manqué la coupe en deux !",
        ("Réclame ta solde : **`/daily`**.",),
        check="daily", hint="Je ne vois pas encore ta solde du jour : tape `/daily` puis reviens ici.",
    ),
    TutorialStep(
        "stats", "💪", "Forger son corps",
        "Ta force ne vient que de toi. À chaque niveau, tu gagnes **un point de stats** à placer : "
        "**+2 attaque**, **+2 défense** ou **+50 PV**. L'équipement et l'arbre ajoutent ensuite un "
        "POURCENTAGE de ce socle : plus il est solide, plus tout le reste compte.",
        ("Ouvre ta feuille de personnage : **`/stats`**, et place un point.",
         "Pas de point à placer ? Tu en gagneras un au prochain niveau : passe à la suite."),
        check="stats", hint="Tu as encore un point à placer : `/stats`, puis un des trois boutons.",
    ),
    TutorialStep(
        "combat", "⚔️", "Le premier sang",
        "Assez parlé ! Dans la **{zone}**, un monstre apparaît régulièrement. Clique sur "
        "**⚔️ Combattre** pour rejoindre le groupe : un compte à rebours dit quand le combat part, "
        "et je te mentionnerai au lancement pour que tu le regardes en direct. Le combat se joue "
        "tout seul, en vidéo — ta préparation fait tout.",
        ("Va dans {zone} et clique **⚔️ Combattre** sur le monstre.",
         "Seul, c'est possible ; à plusieurs, c'est plus sûr : l'XP est entière pour chacun, l'or "
         "est partagé selon ta part du combat.",
         "Tes PV ne remontent qu'ENTRE les combats (régénération), pas pendant. À 0 PV, on ne "
         "peut pas rejoindre : attends ou bois une potion (`/utiliser`)."),
        check="combat", hint="Je n'ai pas encore vu ton premier combat. Le monstre t'attend dans {zone} !",
    ),
    TutorialStep(
        "butin", "🎒", "Le butin du chasseur",
        "Chaque monstre porte **une pièce d'équipement** : vaincs-le et il peut te la laisser, "
        "de **commun** à **mythique**. Il lâche aussi les **matériaux** de sa famille. "
        "Avec deux copies de la même pièce et de la même rareté, **Borak le forgeron** les fusionne "
        "en une rareté supérieure. Dès l'épique, chaque pièce réveille son **passif**.",
        ("Ton sac : **`/inventaire`** · tes pièces : **`/equipement_liste`**.",
         "Équipe une pièce : **`/equiper`** (elle se place toute seule) · ta tenue : **`/equipement`**.",
         "Fusion chez **`/forgeron`** · bonus de panoplie : **`/panoplie`**."),
    ),
    TutorialStep(
        "arbre", "🌳", "L'arbre des voies",
        "À chaque niveau, tu gagnes aussi des **points d'arbre**. Trois voies t'attendent : "
        "**Guerrier** (dégâts), **Gardien** (encaisser, protéger) et **Clerc** (soigner). Plus "
        "loin, chacun choisit **une** spécialisation : Assassin, Rempart ou Soigneur. "
        "Un groupe équilibré — un qui frappe, un qui encaisse, un qui soigne — vient à bout de tout.",
        ("Ouvre ton arbre : **`/arbre`** (Investir, ou la vue web pour tout voir).",
         "Choisis comment ton soigneur vise : **`/tactique`**.",
         "Un reset gratuit par semaine : ne crains pas d'essayer."),
    ),
    TutorialStep(
        "elements", "✨", "Les huit éléments",
        "Chaque monstre a un **élément**. Ton attaque prend toute seule celui qui le frappe le plus "
        "fort, et ta **maîtrise** décide du bonus. Les monstres d'un élément lâchent ses "
        "**essences**, qui montent ton affinité. Mais chacun naît avec des **talents** cachés… "
        "Ma vieille amie **Ysaline** sait les lire. La première lecture est offerte !",
        ("Tes affinités : **`/affinites`**.",
         "Va voir la voyante : **`/voyante`**, et fais lire un talent (le premier est gratuit)."),
        check="voyante", hint="Ysaline n'a encore rien lu pour toi : `/voyante`, choisis un élément.",
    ),
    TutorialStep(
        "quetes", "📋", "Contrats et défis",
        "La guilde affiche chaque jour des **quêtes** taillées pour toi : trois par jour, trois par "
        "semaine. Il y a aussi les **défis** de rôle — DPS, Tank, Soutien — où tout le serveur se "
        "mesure, et la **Tour**, cent étages à gravir seul.",
        ("Tes quêtes : **`/quetes`** et **`/quetes_hebdo`**.",
         "Les défis du jour : **`/defi`** · la tour : **`/tour`** · les classements : **`/classement`**."),
    ),
    TutorialStep(
        "ville", "🏘️", "Les gens de la ville",
        "En ville, tu croiseras **Borak** le forgeron, **Elna** l'alchimiste (potions et élixirs "
        "avec tes matériaux), **Sorn** le marchand (outils et cosmétiques) et **Ysaline**. Entre "
        "aventuriers, on s'échange et on vend à la brocante. Et quand tout le serveur remplit "
        "l'**offrande**, une divinité nous bénit tous pour la journée.",
        ("**`/alchimiste`** · **`/marchand`** · **`/apparence`** (tes cosmétiques).",
         "**`/echange`** · **`/brocante`** · **`/payer`** · **`/offrande`**."),
    ),
    TutorialStep(
        "rangs", "👑", "Rangs, raid et ciel",
        "Quand ta puissance est assez grande, passe l'**épreuve** du rang suivant : réussis celle "
        "de TON rôle face au gardien, et une nouvelle région s'ouvre. Chaque semaine, un **boss** "
        "colossal se dresse : on s'inscrit, et chaque soir le raid l'attaque ensemble. Et lève "
        "les yeux : les nuits de **pleine lune**, les monstres sont plus forts… et plus riches.",
        ("L'épreuve : **`/epreuve`** · le raid : **`/boss moi`** · le ciel : **`/lune`**.",
         "Toutes les commandes : **`/help`**."),
    ),
)


def step_index(code: str) -> int:
    return next((i for i, s in enumerate(STEPS) if s.code == code), 0)
