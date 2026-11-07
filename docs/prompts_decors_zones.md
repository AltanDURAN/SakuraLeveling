# Prompts des décors de zones — C, B, A

Les 11 décors des trois zones ouvertes sans décor : un par élément de zone. Pour l'instant, ces zones affichent la
forêt de la Clairière. Chaque bloc est **complet** : copie-le tel quel, une image par message.

**Même lieu, plusieurs éléments.** Comme le Cimetière ou le Berceau, une zone garde le MÊME lieu et l'élément le
transforme. Fais le 1er décor d'une zone, puis demande les autres dans la même conversation en joignant le 1er et
en ajoutant « même lieu et même cadrage que l'image jointe ».

**Style** : joins au premier message un ou deux décors actuels (`assets/landscapes/cimetiere_abandonne_glace.png`,
`assets/landscapes/berceau_cataclysmique_feu.png`) et ajoute « dans le même style que les images jointes ».

**Format** : vertical. ChatGPT rend du 2:3 et Gemini sait faire du 4:5 ; les deux passent, le cadrage se règle
ensuite sur le site.

**Gemini** met son logo ✦ en bas à droite (les décors actuels l'ont) : rogne-le, ou garde-le hors du cadrage.

**Importer** : renomme le fichier comme indiqué sous chaque titre (le site garde le nom du fichier), puis
Monde › Zones › la zone › « Ajouter un élément » (choisis l'élément) › « Ajouter & composer » : dépose l'image,
règle le cadrage et la ligne de sol avec l'aperçu. Ajoute TOUS les éléments de la zone : un monstre n'apparaît que
sous un élément qui a son décor. Choisis aussi l'un d'eux comme décor par défaut de la zone (fiche de la zone).

## Sanctuaire primordial (rang C)

Forêt millénaire et bêtes sacrées (loup, cerf, serpent, ours, golem de mousse, aigle). Plus majestueux et ancien que
la Clairière, toujours inquiétant.

### Plante — `sanctuaire_primordial_plante.png`

```text
Décor de fond pour un jeu RPG dark fantasy : le Sanctuaire primordial, un lieu sacré au cœur d'une forêt millénaire — arbres colossaux aux racines gigantesques, un cercle de monolithes de pierre gravés de totems d'animaux sacrés (loup, cerf, ours, aigle) autour d'une clairière d'herbe rase. Version PLANTE : la végétation a tout envahi, lianes en fleurs sur les monolithes, fougères géantes, mousse épaisse, spores lumineuses qui flottent, rayons de lumière vert doré qui percent la canopée. Palette dominante : vert émeraude profond, or doux.
Style : peinture numérique détaillée et semi-réaliste, ambiance dark fantasy sombre et atmosphérique, éclairage dramatique, brume, profondeur marquée (premier plan, plan moyen, lointain).
Composition : image verticale (portrait). Le tiers inférieur est un sol dégagé, plat et praticable au centre, où un monstre sera posé (ses pieds vers 85 % de la hauteur) ; les éléments du décor encadrent la scène sur les côtés et au loin ; rien ne masque le centre.
Interdits : aucun personnage, aucune créature, aucun animal, aucun texte, aucun cadre, aucun filigrane, aucune interface.
```

### Terre — `sanctuaire_primordial_terre.png`

```text
Décor de fond pour un jeu RPG dark fantasy : le Sanctuaire primordial, un lieu sacré au cœur d'une forêt millénaire — arbres colossaux aux racines gigantesques, un cercle de monolithes de pierre gravés de totems d'animaux sacrés (loup, cerf, ours, aigle) autour d'une clairière. Version TERRE : le sanctuaire est creusé au fond d'un canyon de roche ocre, monolithes fissurés, énormes rochers couverts de mousse, racines qui fendent la pierre, poussière dorée en suspension, hautes falaises au loin. Palette dominante : ocre, brun chaud, vert mousse.
Style : peinture numérique détaillée et semi-réaliste, ambiance dark fantasy sombre et atmosphérique, éclairage dramatique, brume, profondeur marquée (premier plan, plan moyen, lointain).
Composition : image verticale (portrait). Le tiers inférieur est un sol dégagé, plat et praticable au centre, où un monstre sera posé (ses pieds vers 85 % de la hauteur) ; les éléments du décor encadrent la scène sur les côtés et au loin ; rien ne masque le centre.
Interdits : aucun personnage, aucune créature, aucun animal, aucun texte, aucun cadre, aucun filigrane, aucune interface.
```

### Eau — `sanctuaire_primordial_eau.png`

⚠️ Ce décor ne s'affichera que si un monstre du Sanctuaire reçoit l'élément eau ou n'a plus d'élément fixé : aujourd'hui, aucun n'est concerné (cf. audit du 06/11/2026).

```text
Décor de fond pour un jeu RPG dark fantasy : le Sanctuaire primordial, un lieu sacré au cœur d'une forêt millénaire — arbres colossaux aux racines gigantesques, un cercle de monolithes de pierre gravés de totems d'animaux sacrés (loup, cerf, ours, aigle). Version EAU : une source sacrée, des cascades tombent des falaises dans un lac calme et brumeux à l'arrière-plan, des monolithes se dressent au bord de l'eau ; au premier plan, une berge de pierres plates et d'herbe humide (le sol reste praticable), reflets turquoise, gouttelettes en suspension. Palette dominante : turquoise, bleu-vert, argent.
Style : peinture numérique détaillée et semi-réaliste, ambiance dark fantasy sombre et atmosphérique, éclairage dramatique, brume, profondeur marquée (premier plan, plan moyen, lointain).
Composition : image verticale (portrait). Le tiers inférieur est un sol dégagé, plat et praticable au centre, où un monstre sera posé (ses pieds vers 85 % de la hauteur) ; les éléments du décor encadrent la scène sur les côtés et au loin ; rien ne masque le centre.
Interdits : aucun personnage, aucune créature, aucun animal, aucun texte, aucun cadre, aucun filigrane, aucune interface.
```

### Vent — `sanctuaire_primordial_vent.png`

```text
Décor de fond pour un jeu RPG dark fantasy : le Sanctuaire primordial, un lieu sacré à la lisière d'une forêt millénaire — arbres colossaux, monolithes de pierre gravés de totems d'animaux sacrés (loup, cerf, ours, aigle). Version VENT : un haut plateau balayé par la tempête, herbes hautes couchées par le vent, arbres pliés, feuilles arrachées emportées en tourbillons, nuages qui filent dans un ciel pâle et agité, une grande arche de pierre gravée d'un aigle aux ailes déployées à l'arrière-plan. Palette dominante : gris argenté, vert pâle, blanc.
Style : peinture numérique détaillée et semi-réaliste, ambiance dark fantasy sombre et atmosphérique, éclairage dramatique, brume, profondeur marquée (premier plan, plan moyen, lointain).
Composition : image verticale (portrait). Le tiers inférieur est un sol dégagé, plat et praticable au centre, où un monstre sera posé (ses pieds vers 85 % de la hauteur) ; les éléments du décor encadrent la scène sur les côtés et au loin ; rien ne masque le centre.
Interdits : aucun personnage, aucune créature, aucun animal, aucun texte, aucun cadre, aucun filigrane, aucune interface.
```

## Éclipse éternelle (rang B)

Le domaine d'une noblesse vampirique (goule, loup-garou, sorcière de sang, chevalier de l'éclipse, vampire,
comtesse) sous une éclipse qui ne finit jamais.

### Ténèbre — `eclipse_eternelle_tenebre.png`

```text
Décor de fond pour un jeu RPG dark fantasy : l'Éclipse éternelle, le domaine d'une noblesse vampirique sous une éclipse qui ne finit jamais — un soleil noir cerclé d'un fin anneau de lumière domine le ciel, un château gothique aux flèches acérées sur une falaise au loin, au premier plan une cour pavée devant de hautes grilles de fer forgé, arbres morts et statues de gargouilles sur les côtés. Version TÉNÈBRE : nuit presque totale, brouillard au ras des pavés, quelques fenêtres du château éclairées de rouge, roses noires grimpant sur les grilles, lueurs pourpres et rouge sang. Palette dominante : noir, violet profond, rouge sang.
Style : peinture numérique détaillée et semi-réaliste, ambiance dark fantasy sombre et atmosphérique, éclairage dramatique, brume, profondeur marquée (premier plan, plan moyen, lointain).
Composition : image verticale (portrait). Le tiers inférieur est un sol dégagé, plat et praticable au centre, où un monstre sera posé (ses pieds vers 85 % de la hauteur) ; les éléments du décor encadrent la scène sur les côtés et au loin ; rien ne masque le centre.
Interdits : aucun personnage, aucune créature, aucun animal, aucune chauve-souris, aucun texte, aucun cadre, aucun filigrane, aucune interface.
```

### Lumière — `eclipse_eternelle_lumiere.png`

```text
Décor de fond pour un jeu RPG dark fantasy : l'Éclipse éternelle, le domaine d'une noblesse vampirique sous une éclipse qui ne finit jamais — un soleil noir cerclé d'un anneau de lumière domine le ciel, un château gothique aux flèches acérées sur une falaise au loin, au premier plan une cour pavée, arbres morts et statues de gargouilles sur les côtés. Version LUMIÈRE : la couronne de l'éclipse flamboie et projette des rayons blanc argenté et or pâle à travers les nuages, les ruines d'une cathédrale gothique aux vitraux brillants sur un côté, poussière lumineuse dans l'air ; une lumière belle mais froide et inquiétante. Palette dominante : argent, or pâle, gris bleuté, touches de cramoisi.
Style : peinture numérique détaillée et semi-réaliste, ambiance dark fantasy sombre et atmosphérique, éclairage dramatique, brume, profondeur marquée (premier plan, plan moyen, lointain).
Composition : image verticale (portrait). Le tiers inférieur est un sol dégagé, plat et praticable au centre, où un monstre sera posé (ses pieds vers 85 % de la hauteur) ; les éléments du décor encadrent la scène sur les côtés et au loin ; rien ne masque le centre.
Interdits : aucun personnage, aucune créature, aucun animal, aucun texte, aucun cadre, aucun filigrane, aucune interface.
```

### Glace — `eclipse_eternelle_glace.png`

```text
Décor de fond pour un jeu RPG dark fantasy : l'Éclipse éternelle, le domaine d'une noblesse vampirique sous une éclipse qui ne finit jamais — un soleil noir cerclé d'un anneau de lumière domine le ciel, un château gothique aux flèches acérées sur une falaise au loin, au premier plan une cour pavée devant de hautes grilles de fer forgé, statues de gargouilles sur les côtés. Version GLACE : la cour est gelée, pavés couverts de givre, gargouilles et grilles prises dans la glace, une fontaine figée en glace à l'arrière-plan, stalactites aux balcons du château, neige fine qui tombe sous l'éclipse. Palette dominante : bleu glacier, blanc, noir, reflets argentés.
Style : peinture numérique détaillée et semi-réaliste, ambiance dark fantasy sombre et atmosphérique, éclairage dramatique, brume, profondeur marquée (premier plan, plan moyen, lointain).
Composition : image verticale (portrait). Le tiers inférieur est un sol dégagé, plat et praticable au centre, où un monstre sera posé (ses pieds vers 85 % de la hauteur) ; les éléments du décor encadrent la scène sur les côtés et au loin ; rien ne masque le centre.
Interdits : aucun personnage, aucune créature, aucun animal, aucun texte, aucun cadre, aucun filigrane, aucune interface.
```

## Cimes des Wyrms (rang A)

Les pics où nichent les dragons (kobold, dragonnet, drake de braise, wyverne, dragon de givre, gardien, dragon
ancien). La version feu doit rester une MONTAGNE brûlée : le Berceau est déjà un champ de lave.

### Feu — `cimes_des_wyrms_feu.png`

```text
Décor de fond pour un jeu RPG dark fantasy : les Cimes des Wyrms, des pics montagneux vertigineux où nichent les dragons — une large corniche rocheuse à flanc de montagne, d'immenses ossements de dragon à moitié enfouis sur les côtés, une ancienne porte de pierre sculptée en tête de dragon à l'arrière-plan, des pics acérés à perte de vue. Version FEU : un nid de dragon sur la corniche, roches noircies et ossements calcinés, braises rougeoyantes entre les pierres, un pic fumant au loin, ciel de crépuscule orange et rouge, cendres qui volent ; une montagne brûlée, pas un champ de lave. Palette dominante : orange, rouge braise, noir charbon.
Style : peinture numérique détaillée et semi-réaliste, ambiance dark fantasy sombre et atmosphérique, éclairage dramatique, brume, profondeur marquée (premier plan, plan moyen, lointain).
Composition : image verticale (portrait). Le tiers inférieur est un sol dégagé, plat et praticable au centre, où un monstre sera posé (ses pieds vers 85 % de la hauteur) ; les éléments du décor encadrent la scène sur les côtés et au loin ; rien ne masque le centre.
Interdits : aucun personnage, aucune créature, aucun animal, aucun dragon vivant, aucun texte, aucun cadre, aucun filigrane, aucune interface.
```

### Glace — `cimes_des_wyrms_glace.png`

```text
Décor de fond pour un jeu RPG dark fantasy : les Cimes des Wyrms, des pics montagneux vertigineux où nichent les dragons — une large corniche rocheuse à flanc de montagne, une ancienne porte de pierre sculptée en tête de dragon à l'arrière-plan, des pics acérés à perte de vue. Version GLACE : glacier et neige éternelle, un immense squelette de dragon pris dans un mur de glace bleue sur un côté, falaises de glace, blizzard léger, ciel blanc-gris. Palette dominante : bleu glacier, blanc, gris acier.
Style : peinture numérique détaillée et semi-réaliste, ambiance dark fantasy sombre et atmosphérique, éclairage dramatique, brume, profondeur marquée (premier plan, plan moyen, lointain).
Composition : image verticale (portrait). Le tiers inférieur est un sol dégagé, plat et praticable au centre, où un monstre sera posé (ses pieds vers 85 % de la hauteur) ; les éléments du décor encadrent la scène sur les côtés et au loin ; rien ne masque le centre.
Interdits : aucun personnage, aucune créature, aucun animal, aucun dragon vivant, aucun texte, aucun cadre, aucun filigrane, aucune interface.
```

### Vent — `cimes_des_wyrms_vent.png`

```text
Décor de fond pour un jeu RPG dark fantasy : les Cimes des Wyrms, des pics montagneux vertigineux où nichent les dragons — d'immenses ossements de dragon sur les côtés, une ancienne porte de pierre sculptée en tête de dragon à l'arrière-plan. Version VENT : le plus haut sommet, au-dessus d'une mer de nuages, un plateau de roche nue balayé par des rafales visibles, bannières déchirées et cordes de prières qui claquent sur d'anciens piliers de pierre, ciel immense et tourmenté. Palette dominante : bleu ciel pâle, blanc, gris.
Style : peinture numérique détaillée et semi-réaliste, ambiance dark fantasy sombre et atmosphérique, éclairage dramatique, brume, profondeur marquée (premier plan, plan moyen, lointain).
Composition : image verticale (portrait). Le tiers inférieur est un sol dégagé, plat et praticable au centre, où un monstre sera posé (ses pieds vers 85 % de la hauteur) ; les éléments du décor encadrent la scène sur les côtés et au loin ; rien ne masque le centre.
Interdits : aucun personnage, aucune créature, aucun animal, aucun dragon vivant, aucun texte, aucun cadre, aucun filigrane, aucune interface.
```

### Terre — `cimes_des_wyrms_terre.png`

```text
Décor de fond pour un jeu RPG dark fantasy : les Cimes des Wyrms, des pics montagneux vertigineux où nichent les dragons — une large corniche rocheuse à flanc de montagne, d'immenses ossements de dragon à moitié enfouis, des pics acérés au loin. Version TERRE : l'entrée d'une mine de kobolds creusée dans la montagne, sous un crâne de dragon géant qui sert d'arche à l'arrière-plan, terrasses de roche ocre, échafaudages de bois branlants sur les côtés, cristaux bruns et ambrés incrustés dans la paroi, poussière dans l'air. Palette dominante : ocre, brun, ambre.
Style : peinture numérique détaillée et semi-réaliste, ambiance dark fantasy sombre et atmosphérique, éclairage dramatique, brume, profondeur marquée (premier plan, plan moyen, lointain).
Composition : image verticale (portrait). Le tiers inférieur est un sol dégagé, plat et praticable au centre, où un monstre sera posé (ses pieds vers 85 % de la hauteur) ; les éléments du décor encadrent la scène sur les côtés et au loin ; rien ne masque le centre.
Interdits : aucun personnage, aucune créature, aucun animal, aucun dragon vivant, aucun texte, aucun cadre, aucun filigrane, aucune interface.
```
